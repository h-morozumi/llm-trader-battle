from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Sequence

from .config import DEFAULT_LLMS, JST, UTC
from .storage import dump_json, ensure_week_dir, load_json_optional


@dataclass
class LlmPick:
    model: str
    symbols: List[str]
    picked_at_utc: datetime

    def to_dict(self) -> dict:
        data = asdict(self)
        data["picked_at_utc"] = self.picked_at_utc.astimezone(UTC).isoformat()
        return data


def generate_stub_picks(week_dir: Path, models: Sequence[str] | None = None) -> list[LlmPick]:
    # Placeholder picks. Replace with real LLM calls.
    models = list(models) if models else DEFAULT_LLMS
    base_candidates = ["7203.T", "6758.T", "9984.T", "6861.T", "8035.T"]
    picks: list[LlmPick] = []
    now = datetime.now(tz=JST)
    for idx, model in enumerate(models):
        # simple round-robin choice for determinism
        symbols = [base_candidates[idx % len(base_candidates)], base_candidates[(idx + 2) % len(base_candidates)]]
        picks.append(LlmPick(model=model, symbols=symbols, picked_at_utc=now.astimezone(UTC)))
    save_picks(week_dir, picks)
    return picks


def save_picks(week_dir: Path, picks: Sequence[LlmPick]) -> None:
    ensure_week_dir(week_dir)
    dump_json(week_dir / "picks.json", [p.to_dict() for p in picks])


def load_picks(week_dir: Path) -> list[LlmPick]:
    raw = load_json_optional(week_dir / "picks.json")
    if not raw:
        return []
    result: list[LlmPick] = []
    for entry in raw:
        result.append(
            LlmPick(
                model=entry["model"],
                symbols=list(entry["symbols"]),
                picked_at_utc=datetime.fromisoformat(entry["picked_at_utc"]),
            )
        )
    return result
