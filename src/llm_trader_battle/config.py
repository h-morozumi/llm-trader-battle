from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")

DEFAULT_LLMS = ["gpt", "gemini", "claude", "grok"]


@dataclass(frozen=True)
class WeekWindow:
    week_start: date  # Monday in JST
    week_end: date    # Friday in JST

    def label(self) -> str:
        return self.week_start.isoformat()


def now_jst() -> datetime:
    return datetime.now(tz=JST)


def to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)
