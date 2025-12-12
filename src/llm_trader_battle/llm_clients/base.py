from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from textwrap import dedent
from typing import Iterable, Protocol, Sequence


def _normalize_symbol(sym: str) -> str:
    sym = sym.strip()
    # If LLM returned only digits (common for JP tickers), append .T for TSE.
    if sym.isdigit():
        return f"{sym}.T"
    return sym


@dataclass
class PickRequest:
    llm_name: str
    week_start: date
    max_picks: int = 2
    universe: Sequence[str] | None = None


@dataclass
class PickResponse:
    symbols: list[str]
    reasons: list[str]
    methods: list[str]


class LlmClient(Protocol):
    def generate(self, req: PickRequest) -> PickResponse: ...


def parse_picks_json(text: str) -> PickResponse:
    """Parse JSON of shape {"picks":[{"symbol":"7203.T","reason":"...","method":"..."}, ...]}"""
    def _extract_json_payload(raw: str) -> str:
        s = (raw or "").strip()
        if not s:
            return s
        # Strip markdown code fences if present.
        if s.startswith("```"):
            lines = s.splitlines()
            if lines and lines[0].lstrip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()

        # If extra prose exists, try to carve out the first JSON object.
        if not s.startswith("{"):
            start = s.find("{")
            end = s.rfind("}")
            if 0 <= start < end:
                s = s[start : end + 1].strip()
        return s

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        extracted = _extract_json_payload(text)
        if not extracted:
            raise
        data = json.loads(extracted)
    picks = data.get("picks") if isinstance(data, dict) else None
    if not isinstance(picks, Iterable):
        raise ValueError("invalid picks payload")
    symbols: list[str] = []
    reasons: list[str] = []
    methods: list[str] = []
    for entry in picks:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        if sym:
            symbols.append(_normalize_symbol(str(sym)))
            reasons.append(str(entry.get("reason", "")))
            methods.append(str(entry.get("method", "")))
        if len(symbols) >= 2:
            break
    if not symbols:
        raise ValueError("no symbols parsed")
    return PickResponse(symbols=symbols, reasons=reasons, methods=methods)


def build_prompt(req: PickRequest) -> str:
    """Common prompt to request exactly max_picks tickers with brief reasons in JSON."""
    universe_hint = "" if not req.universe else f"Focus on these symbols if suitable: {', '.join(req.universe)}."
    return dedent(
        f"""
        You are a Japanese equity picker. Choose exactly {req.max_picks} Tokyo Stock Exchange tickers for the week starting {req.week_start}.
        You may pick any listed ticker you judge attractive. {universe_hint}
        Tickers must include the exchange suffix ".T" (example: 7203.T). Do not return raw numbers.
        Respond with JSON only, following schema:
        {{"picks":[{{"symbol":"<ticker>","reason":"<short justification>","method":"<analysis method used>"}}, ...]}}
        "method" should be a short label like "fundamental", "technical", "theme", "news", or similar.
        Write "reason" and "method" in Japanese.
        No extra text or commentary.
        """
    ).strip()
