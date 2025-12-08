from __future__ import annotations

from datetime import date, datetime, timedelta

import jpholiday

from .config import WeekWindow, JST


def week_window_for(dt: datetime) -> WeekWindow:
    # Normalize to JST date and find Monday/Friday for that week.
    jst_date = dt.astimezone(JST).date()
    monday = jst_date - timedelta(days=jst_date.weekday())
    friday = monday + timedelta(days=4)
    return WeekWindow(week_start=monday, week_end=friday)


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    if jpholiday.is_holiday(d):
        return False
    return True


def next_trading_day(start: date) -> date:
    d = start
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d
