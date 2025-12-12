from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List, Sequence

from .config import DEFAULT_LLMS, JST, UTC
from .storage import PICKS_DIR, dump_json, load_json_optional, flat_picks_json_path
from .llm_clients.base import PickRequest
from .llm_clients.claude import ClaudeClient
from .llm_clients.gemini import GeminiClient
from .llm_clients.grok_openai import GrokOpenAIClient
from .llm_clients.openai_azure import AzureOpenAIClient


@dataclass
class LlmPick:
    model: str
    symbols: List[str]
    reasons: List[str]
    methods: List[str]
    picked_at_utc: datetime

    def to_dict(self) -> dict:
        data = asdict(self)
        data["picked_at_utc"] = self.picked_at_utc.astimezone(UTC).isoformat()
        return data


def _client_for(model: str):
    # lazy construct to avoid importing SDKs when not needed
    if model == "gpt":
        return AzureOpenAIClient()
    if model == "grok":
        return GrokOpenAIClient()
    if model == "gemini":
        return GeminiClient()
    if model == "claude":
        return ClaudeClient()
    raise ValueError(f"unsupported model {model}")


def generate_llm_picks(week_dir: Path, week_start: date, models: Sequence[str] | None = None, universe: Sequence[str] | None = None) -> list[LlmPick]:
    models = list(models) if models else DEFAULT_LLMS
    universe = list(universe) if universe else None
    picks: list[LlmPick] = []
    now = datetime.now(tz=JST)
    log_raw = os.environ.get("LLM_TRADER_BATTLE_LOG_LLM_OUTPUT", "").strip().lower() in {"1", "true", "yes", "on"}
    log_tool = os.environ.get("LLM_TRADER_BATTLE_LOG_LLM_TOOL", "").strip().lower() in {"1", "true", "yes", "on"}
    log_tool_trace = os.environ.get("LLM_TRADER_BATTLE_LOG_LLM_TOOL_TRACE", "").strip().lower() in {"1", "true", "yes", "on"}
    for model in models:
        client = _client_for(model)
        resp = client.generate(PickRequest(llm_name=model, week_start=week_start, max_picks=2, universe=universe or []))
        if log_raw and getattr(resp, "raw", None):
            print(f"\n[llm-raw-output] llm={model}\n{resp.raw}\n[/llm-raw-output]\n", file=sys.stderr)
        if log_tool:
            used = getattr(resp, "tool_used", None)
            trace = getattr(resp, "tool_trace", None)
            print(f"[llm-tool-usage] llm={model} tool_used={used}", file=sys.stderr)
            if log_tool_trace and trace is not None:
                import json

                print(json.dumps({"llm": model, "tool_trace": trace}, ensure_ascii=False, indent=2), file=sys.stderr)
        symbols = resp.symbols[:2]
        reasons = resp.reasons[:2] if resp.reasons else [""] * len(symbols)
        methods = resp.methods[:2] if hasattr(resp, "methods") and resp.methods else [""] * len(symbols)
        if len(symbols) < 2:
            raise ValueError(f"insufficient picks returned for {model}")
        picks.append(
            LlmPick(
                model=model,
                symbols=symbols,
                reasons=reasons,
                methods=methods,
                picked_at_utc=now.astimezone(UTC),
            )
        )
    save_picks(week_dir, picks)
    return picks


def save_picks(week_dir: Path, picks: Sequence[LlmPick]) -> None:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    payload = _picks_to_object(week_dir.name, picks)
    dump_json(flat_picks_json_path(week_dir.name), payload)


def week_dir_from_id(week_id: str) -> Path:
    return PICKS_DIR / week_id


def save_week_and_current(week_id: str, picks: Sequence[LlmPick]) -> None:
    week_dir = week_dir_from_id(week_id)
    save_picks(week_dir, picks)
    dump_json(PICKS_DIR / "current.json", _picks_to_object(week_id, picks))


def load_picks(week_dir: Path) -> list[LlmPick]:
    raw = load_json_optional(flat_picks_json_path(week_dir.name))
    return _object_to_picks(raw)


def load_current_picks() -> list[LlmPick]:
    raw = load_json_optional(PICKS_DIR / "current.json")
    return _object_to_picks(raw)


def _picks_to_object(week_id: str, picks: Sequence[LlmPick]) -> dict:
    if not picks:
        return {"week_start": week_id, "picked_at_utc": None, "picks": {}}
    picked_ts = picks[0].picked_at_utc.astimezone(UTC).isoformat()
    obj: dict[str, object] = {
        "week_start": week_id,
        "picked_at_utc": picked_ts,
        "picks": {},
    }
    for pick in picks:
        entries = []
        for idx, sym in enumerate(pick.symbols):
            entries.append(
                {
                    "symbol": sym,
                    "reason": pick.reasons[idx] if idx < len(pick.reasons) else "",
                    "method": pick.methods[idx] if idx < len(pick.methods) else "",
                    "symbol_index": idx,
                }
            )
        obj["picks"][pick.model] = entries
    return obj


def _object_to_picks(raw) -> list[LlmPick]:
    if not raw:
        return []
    picks_field = raw.get("picks", {}) if isinstance(raw, dict) else {}
    picked_ts = raw.get("picked_at_utc") if isinstance(raw, dict) else None
    picked_dt = datetime.fromisoformat(picked_ts) if picked_ts else datetime.now(tz=UTC)

    picks: list[LlmPick] = []
    for model, entries in picks_field.items():
        symbols: list[str] = []
        reasons: list[str] = []
        methods: list[str] = []
        # ensure order by symbol_index if present
        if isinstance(entries, list):
            sorted_entries = sorted(
                [e for e in entries if isinstance(e, dict)], key=lambda e: e.get("symbol_index", 0)
            )
            for e in sorted_entries:
                symbols.append(e.get("symbol", ""))
                reasons.append(e.get("reason", ""))
                methods.append(e.get("method", ""))
        picks.append(LlmPick(model=str(model), symbols=symbols, reasons=reasons, methods=methods, picked_at_utc=picked_dt))
    return sorted(picks, key=lambda p: p.model)
