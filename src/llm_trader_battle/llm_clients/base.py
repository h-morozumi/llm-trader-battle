from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from textwrap import dedent
from typing import Iterable, Protocol, Sequence


import re


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
    raw: str | None = None
    tool_used: bool | None = None
    tool_trace: dict | None = None


class LlmClient(Protocol):
    def generate(self, req: PickRequest) -> PickResponse: ...


def _try_repair_truncated_json(s: str) -> str | None:
    """Attempt to repair a truncated JSON by closing open structures."""
    # Count brackets
    open_braces = s.count("{") - s.count("}")
    open_brackets = s.count("[") - s.count("]")

    if open_braces <= 0 and open_brackets <= 0:
        return None  # Not a truncation issue

    repaired = s.rstrip()
    # Check if we're in the middle of a string (odd number of unescaped quotes)
    in_string = False
    i = 0
    while i < len(repaired):
        c = repaired[i]
        if c == "\\" and i + 1 < len(repaired):
            i += 2
            continue
        if c == '"':
            in_string = not in_string
        i += 1

    if in_string:
        repaired += '"'

    # Remove incomplete key-value pair at end (e.g., ',"key":"incomplete' -> ',"key":"incomplete"')
    # After closing the string, check if we have a trailing incomplete pair
    repaired = repaired.rstrip()

    # Remove trailing comma if present
    if repaired.endswith(","):
        repaired = repaired[:-1]

    # Close brackets and braces in order
    repaired += "]" * open_brackets + "}" * open_braces
    return repaired


def _extract_picks_with_regex(text: str) -> list[dict]:
    """Extract pick objects using regex as fallback when JSON is malformed."""
    picks = []
    # Pattern to find symbol values in the JSON
    symbol_pattern = re.compile(r'"symbol"\s*:\s*"([^"]+)"')
    reason_pattern = re.compile(r'"reason"\s*:\s*"([^"]*)')
    method_pattern = re.compile(r'"method"\s*:\s*"([^"]*)')

    symbols = symbol_pattern.findall(text)
    reasons = reason_pattern.findall(text)
    methods = method_pattern.findall(text)

    for i, sym in enumerate(symbols):
        pick = {
            "symbol": sym,
            "reason": reasons[i] if i < len(reasons) else "",
            "method": methods[i] if i < len(methods) else "",
        }
        picks.append(pick)
    return picks


def parse_picks_json(text: str) -> PickResponse:
    """Parse JSON of shape {"picks":[{"symbol":"7203.T","reason":"...","method":"..."}, ...]}"""
    raw_text = text
    def _strip_code_fences(raw: str) -> str:
        s = (raw or "").strip()
        if not s:
            return s
        if s.startswith("```"):
            lines = s.splitlines()
            if lines and lines[0].lstrip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        return s

    def _parse_first_json_object(raw: str):
        s = _strip_code_fences(raw)
        if not s:
            raise json.JSONDecodeError("Empty input", s, 0)

        # Find the first JSON object in the text and parse only that object,
        # tolerating trailing content (which would otherwise raise Extra data).
        start = s.find("{")
        if start < 0:
            return json.loads(s)
        decoder = json.JSONDecoder()
        try:
            obj, end = decoder.raw_decode(s[start:])
            return obj
        except json.JSONDecodeError:
            # Try to repair truncated JSON
            repaired = _try_repair_truncated_json(s[start:])
            if repaired:
                return json.loads(repaired)
            raise

    try:
        data = _parse_first_json_object(text)
    except json.JSONDecodeError:
        # Last-resort fallback: carve between the first '{' and last '}' then parse.
        s = _strip_code_fences(text)
        start = s.find("{")
        end = s.rfind("}")
        data = None
        if 0 <= start < end:
            try:
                data = json.loads(s[start : end + 1].strip())
            except json.JSONDecodeError:
                # Try repair on the carved portion
                repaired = _try_repair_truncated_json(s[start:])
                if repaired:
                    try:
                        data = json.loads(repaired)
                    except json.JSONDecodeError:
                        pass
        elif start >= 0:
            # No closing brace at all - try repair
            repaired = _try_repair_truncated_json(s[start:])
            if repaired:
                try:
                    data = json.loads(repaired)
                except json.JSONDecodeError:
                    pass

        # Ultimate fallback: regex extraction
        if data is None:
            regex_picks = _extract_picks_with_regex(text)
            if regex_picks:
                data = {"picks": regex_picks}
            else:
                raise ValueError(f"Could not parse picks from LLM response: {text[:500]}")
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
    return PickResponse(symbols=symbols, reasons=reasons, methods=methods, raw=raw_text)


def build_prompt(req: PickRequest) -> str:
    """Common prompt to request exactly max_picks tickers with brief reasons in JSON."""
    universe_hint = "" if not req.universe else f"Focus on these symbols if suitable: {', '.join(req.universe)}."
    return dedent(
        f"""
        You are a Japanese equity picker.
        This is a weekly prediction game run on Sunday morning JST.
        Choose exactly {req.max_picks} Tokyo Stock Exchange tickers for the week starting {req.week_start}.
        Goal: maximize the total return of your {req.max_picks} picks.
        Scoring rule: assume you buy at Monday's open price and sell at Friday's close price for the same week.
        Use ONLY information that would be available by Sunday morning JST (no future or hindsight).
        If available, you may use tools such as web search, browsing URLs, or X search to gather up-to-date public information.
        You may pick any listed ticker you judge attractive. {universe_hint}
        Tickers must include the exchange suffix ".T" (example: 7203.T). Do not return raw numbers.
        Respond with JSON only, following schema:
        {{"picks":[{{"symbol":"<ticker>","reason":"<short justification>","method":"<analysis method used>"}}, ...]}}
        "method" should be a short label like "fundamental", "technical", "theme", "news", or similar.
        Write "reason" and "method" in Japanese.
        No extra text or commentary.
        """
    ).strip()
