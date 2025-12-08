from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import List, Sequence

from .config import DEFAULT_LLMS, JST
from .market_calendar import next_trading_day, week_window_for
from .picks import generate_stub_picks, load_picks
from .prices import fetch_open_close, load_prices, save_prices
from .report import (
    compute_llm_avg,
    compute_llm_overall,
    compute_returns,
    plot_llm_bar,
    plot_llm_line,
    summarize_week,
    save_week_report,
    update_summary,
)
from .storage import DATA_DIR, REPORTS_DIR, ensure_week_dir, load_json_optional


def week_dir_for(week: str) -> Path:
    return DATA_DIR / "weeks" / week


def parse_week(value: str | None) -> str:
    if value:
        return value
    from .config import now_jst

    window = week_window_for(now_jst())
    return window.week_start.isoformat()


def handle_generate_picks(args: argparse.Namespace) -> None:
    week = parse_week(args.week)
    week_dir = week_dir_for(week)
    generate_stub_picks(week_dir, models=args.llms or DEFAULT_LLMS)
    print(f"picks saved to {week_dir / 'picks.json'}")


def handle_fetch_open(args: argparse.Namespace) -> None:
    week = parse_week(args.week)
    week_dir = week_dir_for(week)
    week_start = date.fromisoformat(week)
    open_date = next_trading_day(week_start)
    picks = load_picks(week_dir)
    if not picks:
        raise SystemExit("picks.json is missing; run generate-picks first")
    symbols = {s for p in picks for s in p.symbols}
    if not symbols:
        raise SystemExit("no symbols to fetch")
    prices = fetch_open_close(symbols, open_date, open_date)
    save_prices(week_dir, "prices_open", prices)
    print(f"open prices saved to {week_dir / 'prices_open.json'}")


def handle_fetch_close(args: argparse.Namespace) -> None:
    week = parse_week(args.week)
    week_dir = week_dir_for(week)
    week_start = date.fromisoformat(week)
    open_date = next_trading_day(week_start)
    close_date = next_trading_day(week_start + timedelta(days=4))
    picks = load_picks(week_dir)
    if not picks:
        raise SystemExit("picks.json is missing; run generate-picks first")
    symbols = {s for p in picks for s in p.symbols}
    if not symbols:
        raise SystemExit("no symbols to fetch")
    fresh = fetch_open_close(symbols, open_date, close_date)
    existing_open = load_prices(week_dir, "prices_open") or {}
    merged = {}
    for sym in symbols:
        merged[sym] = {
            "open": existing_open.get(sym, {}).get("open") or fresh.get(sym, {}).get("open"),
            "close": fresh.get(sym, {}).get("close"),
        }
    save_prices(week_dir, "prices", merged)
    print(f"final prices saved to {week_dir / 'prices.json'}")


def handle_report(args: argparse.Namespace) -> None:
    week = parse_week(args.week)
    week_dir = week_dir_for(week)
    picks = load_json_optional(week_dir / "picks.json") or []
    prices = load_prices(week_dir, "prices") or {}
    content = summarize_week(week, picks, prices)

    # chart for current week
    returns = compute_returns(prices)
    llm_avg_current = compute_llm_avg(picks, returns)
    week_chart_path = week_dir / "llm_week.png"
    valid_week = {k: v for k, v in llm_avg_current.items() if v is not None}
    plot_llm_bar(valid_week, f"LLM Avg Returns ({week})", week_chart_path)
    if week_chart_path.exists():
        content += f"\n![LLM weekly returns]({week_chart_path.name})\n"
    save_week_report(week_dir, content)

    # update summary across weeks (per LLM)
    all_weeks: List[str] = []
    llm_names: set[str] = set()
    summaries: Dict[str, Dict[str, float | None]] = {}
    for child in (DATA_DIR / "weeks").glob("*"):
        if child.is_dir():
            w = child.name
            all_weeks.append(w)
            picks_candidate = load_json_optional(child / "picks.json") or []
            prices_candidate = load_json_optional(child / "prices.json") or {}
            r = compute_returns(prices_candidate)
            scores = compute_llm_avg(picks_candidate, r)
            summaries[w] = scores
            llm_names.update(scores.keys())
    # ensure current week is included even if not yet saved under data/weeks
    if week not in summaries:
        summaries[week] = llm_avg_current
    llm_names.update(llm_avg_current.keys())
    llm_list = sorted(llm_names)

    # overall chart across weeks per LLM
    overall = compute_llm_overall(summaries)
    summary_chart = REPORTS_DIR / "summary.png"
    plot_llm_line(all_weeks, llm_list, summaries, "LLM Avg Returns by Week", summary_chart)

    update_summary(all_weeks, llm_list, summaries, chart_path=summary_chart if summary_chart.exists() else None)
    print(f"report saved to {week_dir / 'result.md'} and {REPORTS_DIR / 'summary.md'}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LLM trader battle utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pick = sub.add_parser("generate-picks", help="Generate placeholder picks (replace with real LLM calls)")
    p_pick.add_argument("--week", type=str, help="Week start date (YYYY-MM-DD, Monday in JST)")
    p_pick.add_argument("--llms", nargs="+", help="LLM model names")
    p_pick.set_defaults(func=handle_generate_picks)

    p_open = sub.add_parser("fetch-open", help="Fetch Monday open prices")
    p_open.add_argument("--week", type=str, help="Week start date (YYYY-MM-DD)")
    p_open.set_defaults(func=handle_fetch_open)

    p_close = sub.add_parser("fetch-close", help="Fetch Friday close prices and merge")
    p_close.add_argument("--week", type=str, help="Week start date (YYYY-MM-DD)")
    p_close.set_defaults(func=handle_fetch_close)

    p_report = sub.add_parser("report", help="Generate weekly and cumulative reports")
    p_report.add_argument("--week", type=str, help="Week start date (YYYY-MM-DD)")
    p_report.set_defaults(func=handle_report)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
