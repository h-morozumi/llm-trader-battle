from __future__ import annotations

import argparse
from datetime import date, timedelta
from typing import Dict, List, Sequence

from .config import DEFAULT_LLMS, JST
from .market_calendar import next_monday, week_start_for, is_trading_day, is_week_final_trading_day, week_final_trading_day
from .picks import generate_llm_picks, load_current_picks, save_week_and_current, week_dir_from_id
from .prices import fetch_open_close, load_daily_prices, save_daily_prices
from .report import (
    compute_llm_avg,
    find_week_buy_prices,
    plot_llm_bar,
    plot_llm_line,
    llm_model_map,
    save_daily_result,
    summarize_daily,
    summarize_week_final,
    update_month_summary,
    save_week_final_report,
)
from .storage import PICKS_DIR, PRICES_DIR, RESULTS_DIR, REPORTS_DIR, load_json_optional


def parse_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    from .config import now_jst

    return now_jst().date()


def handle_predict(args: argparse.Namespace) -> None:
    target_monday = date.fromisoformat(args.week_start) if args.week_start else next_monday(parse_date(None))
    week_id = target_monday.isoformat()
    llms = args.llms or ([args.llm] if getattr(args, "llm", None) else None) or DEFAULT_LLMS
    picks = generate_llm_picks(week_dir_from_id(week_id), target_monday, models=llms, universe=None)
    save_week_and_current(week_id, picks)
    print(f"picks saved to {PICKS_DIR / week_id} and current.json")


def handle_fetch_daily(args: argparse.Namespace) -> None:
    target = parse_date(args.date)
    if not is_trading_day(target):
        print(f"{target} is not a trading day; skip fetch")
        return
    picks = load_current_picks()
    if not picks:
        raise SystemExit("current picks not found; run predict first")
    symbols = {s for p in picks for s in p.symbols}
    if not symbols:
        raise SystemExit("no symbols to fetch")
    prices = fetch_open_close(symbols, target)
    save_daily_prices(target, prices)
    print(f"prices saved to {PRICES_DIR / target.isoformat() / 'prices.json'}")


def handle_aggregate_daily(args: argparse.Namespace) -> None:
    target = parse_date(args.date)
    if not is_trading_day(target):
        print(f"{target} is not a trading day; skip aggregate")
        return
    week_start = week_start_for(target)
    picks = load_current_picks()
    if not picks:
        raise SystemExit("current picks not found; run predict first")
    today_prices = load_daily_prices(target)
    if not today_prices:
        raise SystemExit("today's prices not found; run fetch-daily first")
    symbols = [s for p in picks for s in p.symbols]
    buy_prices = find_week_buy_prices(symbols, week_start, target)
    returns_per_symbol: Dict[str, Dict[str, float | None]] = {}
    for s in symbols:
        returns_per_symbol[s] = {
            "buy_open": buy_prices.get(s),
            "close": today_prices.get(s, {}).get("close") if isinstance(today_prices.get(s), dict) else None,
        }

    pick_dicts = [{"model": p.model, "symbols": p.symbols} for p in picks]
    content = summarize_daily(target, pick_dicts, today_prices, {s: returns_per_symbol[s]["buy_open"] for s in returns_per_symbol})
    llm_avg: Dict[str, float | None] = {}
    for p in picks:
        vals = []
        for s in p.symbols:
            buy = returns_per_symbol[s]["buy_open"]
            close = returns_per_symbol[s]["close"]
            if buy is not None and close is not None:
                vals.append((close - buy) / buy)
        llm_avg[p.model] = sum(vals) / len(vals) if vals else None

    payload = {
        "date": target.isoformat(),
        "llm_models": {k: v.get("model") for k, v in llm_model_map(sorted(llm_avg.keys())).items()},
        "llm_avg": llm_avg,
        "per_symbol": returns_per_symbol,
    }
    save_daily_result(target, content, payload)

    # week-final report (generated only on the week's last trading day)
    if is_week_final_trading_day(target):
        week_end = target
        week_prices: Dict[str, Dict[str, float | None]] = {}
        for s in symbols:
            week_prices[s] = {
                "open": returns_per_symbol[s]["buy_open"],
                "close": returns_per_symbol[s]["close"],
            }
        week_pick_dicts = [{"model": p.model, "symbols": p.symbols} for p in picks]
        week_md = summarize_week_final(week_start, week_end, week_pick_dicts, week_prices)
        save_week_final_report(week_start, week_md)

    # monthly summary update
    month = target.strftime("%Y%m")
    month_prefix = target.strftime("%Y-%m")
    daily_llm: Dict[str, Dict[str, float | None]] = {}
    llm_names: set[str] = set()
    for child in RESULTS_DIR.glob("result-*.json"):
        day = child.stem.replace("result-", "")
        if not day.startswith(month_prefix):
            continue
        data = load_json_optional(child) or {}
        llm_avg_day = data.get("llm_avg", {})
        daily_llm[day] = llm_avg_day
        llm_names.update(llm_avg_day.keys())
    # ensure current day is included
    daily_llm[target.isoformat()] = llm_avg
    llm_names.update(llm_avg.keys())
    # 非取引日（全LLM None）をグラフ・表から除外して間延びを防ぐ
    filtered_daily_llm = {d: v for d, v in daily_llm.items() if any(val is not None for val in v.values())}
    llm_list = sorted(llm_names)

    # holdings (week start→end, per model)
    holdings: list[dict[str, object]] = []
    for picks_file in PICKS_DIR.glob("picks-*.json"):
        week_id = picks_file.stem.replace("picks-", "")
        if not week_id.startswith(month_prefix):
            continue
        picks_data = load_json_optional(picks_file) or {}
        picks_map = picks_data.get("picks", {}) if isinstance(picks_data, dict) else {}
        week_start = week_id
        last = week_final_trading_day(date.fromisoformat(week_id))
        week_end = (last or (date.fromisoformat(week_id) + timedelta(days=4))).isoformat()
        for model, entries in picks_map.items():
            if not isinstance(entries, list):
                continue
            picks_list = []
            for e in entries:
                if not isinstance(e, dict):
                    continue
                picks_list.append(
                    {
                        "symbol": e.get("symbol", ""),
                        "reason": e.get("reason", ""),
                        "method": e.get("method", ""),
                    }
                )
            holdings.append(
                {
                    "week_start": week_start,
                    "week_end": week_end,
                    "model": str(model),
                    "picks": picks_list,
                }
            )

    chart_path = REPORTS_DIR / month / "summary.png"
    days_sorted = sorted(filtered_daily_llm.keys())

    # mark week-final trading days in the monthly table
    week_finals: set[str] = set()
    for d in filtered_daily_llm.keys():
        try:
            dd = date.fromisoformat(d)
        except ValueError:
            continue
        if is_week_final_trading_day(dd):
            week_finals.add(d)

    plot_llm_line(days_sorted, llm_list, filtered_daily_llm, f"LLM Returns {month}", chart_path, even_spacing=True)
    update_month_summary(
        month,
        llm_list,
        filtered_daily_llm,
        chart_path=chart_path if chart_path.exists() else None,
        holdings=holdings if holdings else None,
        week_finals=week_finals if week_finals else None,
    )
    print(f"results saved to {RESULTS_DIR / target.isoformat()} and reports/{month}/summary.md")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LLM trader battle utilities (daily flow)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pick = sub.add_parser("predict", help="Generate picks for upcoming week (run on weekend)")
    p_pick.add_argument("--week-start", type=str, help="Week start Monday (YYYY-MM-DD). Default: next Monday from today (JST)")
    p_pick.add_argument("--llms", nargs="+", help="LLM model names")
    p_pick.add_argument("--llm", help="LLM model name (alias for --llms with single value)")
    p_pick.set_defaults(func=handle_predict)

    p_fetch = sub.add_parser("fetch-daily", help="Fetch today's open/close for current picks")
    p_fetch.add_argument("--date", type=str, help="Target date (YYYY-MM-DD, JST)")
    p_fetch.set_defaults(func=handle_fetch_daily)

    p_agg = sub.add_parser("aggregate-daily", help="Aggregate returns using first trading day's open and today's close")
    p_agg.add_argument("--date", type=str, help="Target date (YYYY-MM-DD, JST)")
    p_agg.set_defaults(func=handle_aggregate_daily)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
