from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable

import pandas as pd
import yfinance as yf

from .config import JST, UTC
from .storage import PRICES_DIR, dump_json, load_json_optional, flat_prices_json_path


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


def fetch_open_close(symbols: Iterable[str], target_date: date) -> Dict[str, Dict[str, float | None]]:
    df = _fetch_daily(symbols, target_date, target_date)
    result: Dict[str, Dict[str, float | None]] = {}
    for symbol in symbols:
        result[symbol] = {
            "open": _extract_price(df, symbol, target_date, "Open"),
            "high": _extract_price(df, symbol, target_date, "High"),
            "low": _extract_price(df, symbol, target_date, "Low"),
            "close": _extract_price(df, symbol, target_date, "Close"),
        }
    return result


def daily_path(d: date) -> Path:
    return PRICES_DIR / d.isoformat() / "prices.json"


def save_daily_prices(d: date, payload) -> None:
    dump_json(flat_prices_json_path(d), payload)
    dump_json(flat_prices_json_path(d), payload)


def load_daily_prices(d: date):
    return load_json_optional(flat_prices_json_path(d))

