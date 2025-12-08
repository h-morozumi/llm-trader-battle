from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")


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
