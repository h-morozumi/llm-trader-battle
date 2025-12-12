from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Mapping

import matplotlib.pyplot as plt
from matplotlib import ticker as mticker
import yfinance as yf

from .prices import load_daily_prices
from .storage import REPORTS_DIR, RESULTS_DIR, dump_json, flat_result_json_path
from .market_calendar import trading_days_in_week


@lru_cache(maxsize=2048)
def _company_name(symbol: str) -> str | None:
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:  # noqa: BLE001
        return None
    name = info.get("shortName") or info.get("longName") or info.get("name")
    return str(name).strip() if name else None


def _format_symbol(symbol: str) -> str:
    name = _company_name(symbol)
    return f"{symbol} ({name})" if name else symbol


def compute_returns(prices: Dict[str, Dict[str, float | None]]):
    returns: Dict[str, float | None] = {}
    for symbol, values in prices.items():
        open_p = values.get("open")
        close_p = values.get("close")
        if open_p is None or close_p is None:
            returns[symbol] = None
        else:
            returns[symbol] = (close_p - open_p) / open_p
    return returns


def compute_llm_avg(picks: List[dict], returns: Mapping[str, float | None]) -> Dict[str, float | None]:
    per_model: Dict[str, float | None] = {}
    for pick in picks:
        model = pick.get("model")
        symbols = pick.get("symbols", [])
        vals = [returns.get(s) for s in symbols if returns.get(s) is not None]
        per_model[model] = sum(vals) / len(vals) if vals else None
    return per_model


def plot_llm_bar(data: Dict[str, float], title: str, output_path: Path) -> None:
    if not data:
        return
    labels = list(data.keys())
    values = [data[k] for k in labels]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(labels, values, color="#4a90e2")
    ax.set_ylabel("Return")
    ax.set_title(title)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_llm_line(weeks: List[str], llms: List[str], llm_summaries: Dict[str, Dict[str, float | None]], title: str, output_path: Path, even_spacing: bool = False) -> None:
    if not weeks or not llms:
        return
    fig, ax = plt.subplots(figsize=(8, 4))

    if even_spacing:
        x_vals = list(range(len(weeks)))
        x_labels = weeks
    else:
        x_vals = [date.fromisoformat(w) for w in weeks]
        x_labels = None

    for llm in llms:
        series = [llm_summaries.get(w, {}).get(llm) for w in weeks]
        if all(v is None for v in series):
            continue
        ys = [v if v is not None else float("nan") for v in series]
        ax.plot(x_vals, ys, marker="o", label=llm)

    ax.set_title(title)
    ax.set_ylabel("Return")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.legend()

    if even_spacing and x_labels:
        ax.set_xticks(x_vals)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
    else:
        fig.autofmt_xdate()

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def compute_llm_overall(llm_summaries: Dict[str, Dict[str, float | None]]) -> Dict[str, float | None]:
    accum: Dict[str, List[float]] = {}
    for week_scores in llm_summaries.values():
        for llm, val in week_scores.items():
            if val is None:
                continue
            accum.setdefault(llm, []).append(val)
    return {llm: (sum(vals) / len(vals) if vals else None) for llm, vals in accum.items()}


def find_week_buy_prices(symbols: List[str], week_start: date, until: date) -> Dict[str, float | None]:
    buys: Dict[str, float | None] = {s: None for s in symbols}
    for d in trading_days_in_week(week_start):
        if d > until:
            break
        day_prices = load_daily_prices(d) or {}
        for s in symbols:
            if buys[s] is None:
                val = day_prices.get(s, {}).get("open") if isinstance(day_prices.get(s), dict) else None
                if val is not None:
                    buys[s] = val
        if all(v is not None for v in buys.values()):
            break
    return buys


def summarize_daily(target_date: date, picks: List[dict], prices_today: Dict[str, Dict[str, float | None]], buy_prices: Dict[str, float | None]) -> str:
    returns = compute_returns({k: {"open": buy_prices.get(k), "close": prices_today.get(k, {}).get("close")} for k in buy_prices})
    lines: List[str] = []
    lines.append(f"# Daily Result {target_date.isoformat()}")
    lines.append("")
    lines.append("| LLM | Symbol 1 | Symbol 2 | Buy(Open) | Close(today) | Return |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for pick in picks:
        symbols = pick["symbols"]
        s1_disp = _format_symbol(symbols[0])
        s2_disp = _format_symbol(symbols[1])
        b1 = buy_prices.get(symbols[0])
        c1 = prices_today.get(symbols[0], {}).get("close")
        r1 = returns.get(symbols[0])
        b2 = buy_prices.get(symbols[1])
        c2 = prices_today.get(symbols[1], {}).get("close")
        r2 = returns.get(symbols[1])
        avg_ret = None
        valid = [r for r in (r1, r2) if r is not None]
        if valid:
            avg_ret = sum(valid) / len(valid)
        lines.append(
            "| {model} | {s1} | {s2} | {b1:.2f} | {c1:.2f} | {r1:.2%} |".format(
                model=pick["model"],
                s1=s1_disp,
                s2=s2_disp,
                b1=b1 or 0.0,
                c1=c1 or 0.0,
                r1=r1 or 0.0,
            )
        )
        lines.append(
            "|  |  |  | {b2:.2f} | {c2:.2f} | {r2:.2%} |".format(
                b2=b2 or 0.0,
                c2=c2 or 0.0,
                r2=r2 or 0.0,
            )
        )
        avg_str = f"{avg_ret:.2%}" if avg_ret is not None else "N/A"
        lines.append(f"|  |  |  |  |  | Avg: {avg_str} |")
    lines.append("")
    return "\n".join(lines)


def summarize_week(week: str, picks: List[dict], prices: Dict[str, Dict[str, float | None]]) -> str:
    returns = compute_returns(prices)
    lines: List[str] = []
    lines.append(f"# Week {week} Result")
    lines.append("")
    lines.append("| LLM | Symbol 1 | Symbol 2 | Open | Close | Return |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for pick in picks:
        symbols = pick["symbols"]
        s1_disp = _format_symbol(symbols[0])
        s2_disp = _format_symbol(symbols[1])
        open1 = prices.get(symbols[0], {}).get("open")
        close1 = prices.get(symbols[0], {}).get("close")
        ret1 = returns.get(symbols[0])
        open2 = prices.get(symbols[1], {}).get("open")
        close2 = prices.get(symbols[1], {}).get("close")
        ret2 = returns.get(symbols[1])
        avg_ret = None
        valid = [r for r in (ret1, ret2) if r is not None]
        if valid:
            avg_ret = sum(valid) / len(valid)
        lines.append(
            "| {model} | {s1} | {s2} | {o1:.2f} | {c1:.2f} | {r1:.2%} |".format(
                model=pick["model"],
                s1=s1_disp,
                s2=s2_disp,
                o1=open1 or 0.0,
                c1=close1 or 0.0,
                r1=ret1 or 0.0,
            )
        )
        lines.append(
            "|  |  |  | {o2:.2f} | {c2:.2f} | {r2:.2%} |".format(
                o2=open2 or 0.0,
                c2=close2 or 0.0,
                r2=ret2 or 0.0,
            )
        )
        avg_str = f"{avg_ret:.2%}" if avg_ret is not None else "N/A"
        lines.append(f"|  |  |  |  |  | Avg: {avg_str} |")
    lines.append("")
    return "\n".join(lines)


def save_week_report(week_dir: Path, content: str) -> Path:
    path = week_dir / "result.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def update_summary(all_weeks: List[str], llms: List[str], llm_summaries: Dict[str, Dict[str, float | None]], chart_path: Path | None = None) -> Path:
    lines: List[str] = []
    lines.append("# Summary")
    lines.append("")
    header = "| Week | " + " | ".join(llms) + " |"
    sep = "| --- | " + " | ".join(["---"] * len(llms)) + " |"
    lines.append(header)
    lines.append(sep)
    for week in sorted(all_weeks):
        row = [week]
        scores = llm_summaries.get(week, {})
        for llm in llms:
            value = scores.get(llm)
            row.append(f"{value:.2%}" if value is not None else "N/A")
        lines.append("| " + " | ".join(row) + " |")
    if chart_path:
        rel = chart_path.relative_to(REPORTS_DIR)
        lines.append("")
        lines.append(f"![LLM overall returns]({rel.as_posix()})")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = REPORTS_DIR / "summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_path


def save_daily_result(target_date: date, content: str, payload) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = RESULTS_DIR / f"result-{target_date.isoformat()}.md"
    md_path.write_text(content, encoding="utf-8")
    dump_json(flat_result_json_path(target_date), payload)
    return md_path


def update_month_summary(
    month: str,
    llms: List[str],
    daily_llm: Dict[str, Dict[str, float | None]],
    chart_path: Path | None = None,
    holdings: list[dict[str, str]] | None = None,
) -> Path:
    lines: List[str] = []
    lines.append(f"# Summary {month}")
    lines.append("")
    header = "| Date | " + " | ".join(llms) + " |"
    sep = "| --- | " + " | ".join(["---"] * len(llms)) + " |"
    lines.append(header)
    lines.append(sep)
    for day in sorted(daily_llm.keys()):
        row = [day]
        scores = daily_llm.get(day, {})
        for llm in llms:
            value = scores.get(llm)
            row.append(f"{value:.2%}" if value is not None else "N/A")
        lines.append("| " + " | ".join(row) + " |")
    if chart_path:
        lines.append("")
        lines.append(f"![LLM monthly returns](summary.png)")

    if holdings:
        lines.append("")
        lines.append("## Holdings (week start → end)")
        lines.append("")
        lines.append("| Week | Model | Symbols |")
        lines.append("| --- | --- | --- |")
        for h in sorted(holdings, key=lambda x: (x.get("week_start", ""), x.get("model", ""))):
            week = f"{h.get('week_start', '')}→{h.get('week_end', '')}"
            model = h.get("model", "")
            symbols_raw = h.get("symbols", "")
            symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
            symbols_disp = ", ".join(_format_symbol(s) for s in symbols) if symbols else symbols_raw
            lines.append(f"| {week} | {model} | {symbols_disp} |")

    month_dir = REPORTS_DIR / month
    month_dir.mkdir(parents=True, exist_ok=True)
    summary_path = month_dir / "summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_path
