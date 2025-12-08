from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Iterable

import pandas as pd
import yfinance as yf

from .config import JST, UTC
from .storage import dump_json, ensure_week_dir, load_json_optional


def _fetch_daily(symbols: Iterable[str], start: date, end: date) -> pd.DataFrame:
    # yfinance returns timezone-aware index when auto_adjust is False.
    df = yf.download(
        tickers=list(symbols),
        start=start,
        end=end + pd.Timedelta(days=1),
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        # Flatten multiindex columns for consistent access
        df.columns = [f"{c[0]}__{c[1]}" for c in df.columns]
    if not df.index.tz:
        df = df.tz_localize(UTC)
    df = df.tz_convert(JST)
    return df


def _extract_price(df: pd.DataFrame, symbol: str, d: date, field: str) -> float | None:
    key = f"{symbol}__{field}"
    try:
        series = df.loc[str(d), key]
        if isinstance(series, pd.Series):
            return float(series.iloc[0])
        return float(series)
    except KeyError:
        return None


def fetch_open_close(symbols: Iterable[str], open_date: date, close_date: date) -> Dict[str, Dict[str, float | None]]:
    df = _fetch_daily(symbols, open_date, close_date)
    result: Dict[str, Dict[str, float | None]] = {}
    for symbol in symbols:
        result[symbol] = {
            "open": _extract_price(df, symbol, open_date, "Open"),
            "close": _extract_price(df, symbol, close_date, "Close"),
        }
    return result


def save_prices(week_dir, name: str, payload) -> None:
    ensure_week_dir(week_dir)
    dump_json(week_dir / f"{name}.json", payload)


def load_prices(week_dir, name: str):
    return load_json_optional(week_dir / f"{name}.json")
