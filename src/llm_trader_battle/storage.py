from __future__ import annotations

import json
from pathlib import Path
from datetime import date
from typing import Any

DATA_DIR = Path("data")
PICKS_DIR = DATA_DIR / "picks"
PRICES_DIR = DATA_DIR / "prices"
RESULTS_DIR = DATA_DIR / "result"
REPORTS_DIR = Path("reports")
CALENDAR_DIR = DATA_DIR / "calendar"
MANUAL_CLOSED_DATES_PATH = CALENDAR_DIR / "manual_closed_dates.json"


def flat_prices_json_path(d: date) -> Path:
    return PRICES_DIR / f"prices-{d.isoformat()}.json"


def flat_picks_json_path(week_id: str) -> Path:
    return PICKS_DIR / f"picks-{week_id}.json"


def flat_result_json_path(d: date) -> Path:
    return RESULTS_DIR / f"result-{d.isoformat()}.json"


def ensure_week_dir(week_dir: Path) -> None:
    week_dir.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json_optional(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
