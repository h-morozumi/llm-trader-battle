from __future__ import annotations

import os

from google import genai

from .base import LlmClient, PickRequest, PickResponse, build_prompt, parse_picks_json


def _build_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3-pro-preview")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    client = genai.Client(api_key=api_key)
    return client, model_name


def _response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "reason": {"type": "string"},
                        "method": {"type": "string"},
                    },
                    "required": ["symbol", "reason"],
                },
                "minItems": 1,
            }
        },
        "required": ["picks"],
    }


def _safe_model_dump(obj):
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # noqa: BLE001
                return None
    return None


def _extract_tool_trace(resp) -> tuple[bool | None, dict | None]:
    dump = _safe_model_dump(resp)
    if not isinstance(dump, dict):
        return None, None

    grounding = None
    candidates = dump.get("candidates")
    candidate0_keys: list[str] | None = None
    citation = None
    url_ctx = None
    if isinstance(candidates, list) and candidates:
        cand0 = candidates[0] if isinstance(candidates[0], dict) else None
        if cand0 and isinstance(cand0, dict):
            candidate0_keys = sorted(list(cand0.keys()))
            grounding = cand0.get("grounding_metadata") or cand0.get("groundingMetadata")
            citation = cand0.get("citation_metadata") or cand0.get("citationMetadata")
            url_ctx = cand0.get("url_context_metadata") or cand0.get("urlContextMetadata")
    if grounding is None:
        grounding = dump.get("grounding_metadata") or dump.get("groundingMetadata")

    tool_used = bool(grounding) or bool(citation) or bool(url_ctx)
    trace: dict[str, object] = {
        "tools_configured": ["google_search", "url_context"],
        "response_keys": sorted(list(dump.keys())),
        "candidate0_keys": candidate0_keys,
        "grounding_metadata_present": bool(grounding),
        "citation_metadata_present": bool(citation),
        "url_context_metadata_present": bool(url_ctx),
    }
    if isinstance(url_ctx, dict):
        trace["url_context_metadata_keys"] = sorted(list(url_ctx.keys()))
    if isinstance(citation, dict):
        trace["citation_metadata_keys"] = sorted(list(citation.keys()))
    if isinstance(grounding, dict):
        # Keep this small but useful; include keys and any obvious query list.
        trace["grounding_metadata_keys"] = sorted(list(grounding.keys()))
        for key in ("web_search_queries", "webSearchQueries", "search_queries", "searchQueries"):
            if key in grounding:
                trace["search_queries"] = grounding.get(key)
                break
    return tool_used, trace


class GeminiClient(LlmClient):
    def __init__(self) -> None:
        self._client, self._model_name = _build_client()

    def generate(self, req: PickRequest) -> PickResponse:
        prompt = build_prompt(req)
        resp = self._client.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config={
                "tools": [
                    {"google_search": {}},
                    {"url_context": {}},
                ],
                "response_mime_type": "application/json",
                "response_json_schema": _response_schema(),
            },
        )
        parsed = parse_picks_json(resp.text)
        used, trace = _extract_tool_trace(resp)
        parsed.tool_used = used
        parsed.tool_trace = trace
        return parsed
