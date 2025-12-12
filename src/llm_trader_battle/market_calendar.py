from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache

import jpholiday

from .config import WeekWindow, JST
from .storage import MANUAL_CLOSED_DATES_PATH, load_json_optional


def week_window_for(dt: datetime) -> WeekWindow:
    # Normalize to JST date and find Monday/Friday for that week.
    jst_date = dt.astimezone(JST).date()
    monday = jst_date - timedelta(days=jst_date.weekday())
    friday = monday + timedelta(days=4)
    return WeekWindow(week_start=monday, week_end=friday)


def week_start_for(d: date) -> date:
    return d - timedelta(days=d.weekday())


def next_monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7 or 7)


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    if jpholiday.is_holiday(d):
        return False
    if d in manual_closed_dates():
        return False
    return True


def next_trading_day(start: date) -> date:
    d = start
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def trading_days_in_week(week_start: date) -> list[date]:
    days: list[date] = []
    for offset in range(7):
        candidate = week_start + timedelta(days=offset)
        if is_trading_day(candidate):
            days.append(candidate)
    return days


def week_final_trading_day(week_start: date) -> date | None:
    """Return the last trading day within the Mon→Sun window starting at week_start."""
    days = trading_days_in_week(week_start)
    return max(days) if days else None


def is_week_final_trading_day(d: date) -> bool:
    ws = week_start_for(d)
    last = week_final_trading_day(ws)
    return last == d


@lru_cache
def manual_closed_dates() -> set[date]:
    data = load_json_optional(MANUAL_CLOSED_DATES_PATH)
    if not data:
        return set()
    if not isinstance(data, list):
        return set()

    closed: set[date] = set()
    for raw in data:
        try:
            closed.add(date.fromisoformat(raw))
        except ValueError:
            continue
    return closed
