from __future__ import annotations

import os

from xai_sdk import Client as XaiClient
from xai_sdk.search import SearchParameters, web_source, x_source
from xai_sdk.proto import chat_pb2

from .base import LlmClient, PickRequest, PickResponse, build_prompt, parse_picks_json


def _build_client() -> XaiClient:
    api_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")
    base_url = os.environ.get("GROK_ENDPOINT") or os.environ.get("XAI_ENDPOINT")
    if not api_key:
        raise RuntimeError("Grok/XAI API key not set (GROK_API_KEY or XAI_API_KEY)")
    if base_url:
        return XaiClient(api_key=api_key, base_url=base_url)
    return XaiClient(api_key=api_key)


class GrokOpenAIClient(LlmClient):
    def __init__(self) -> None:
        self._client = _build_client()
        self._model = os.environ.get("GROK_MODEL", "grok-4")

    def generate(self, req: PickRequest) -> PickResponse:
        prompt = build_prompt(req)
        # Enable web/X search via search_parameters; response_format enforces JSON
        search_params = SearchParameters(sources=[web_source(), x_source()], mode="auto")
        messages = [
            chat_pb2.Message(
                role=chat_pb2.MessageRole.ROLE_USER,
                content=[chat_pb2.Content(text=prompt)],
            )
        ]
        chat = self._client.chat.create(
            model=self._model,
            messages=messages,
            max_tokens=400,
            response_format="json_object",
            search_parameters=search_params,
        )
        resp = chat.sample()
        parsed = parse_picks_json(resp.content)
        citations = getattr(resp, "citations", None)
        tool_calls = getattr(resp, "tool_calls", None)
        usage = getattr(resp, "usage", None)
        num_sources_used = getattr(usage, "num_sources_used", None) if usage is not None else None

        used: bool | None
        if isinstance(num_sources_used, int):
            used = num_sources_used > 0
        elif isinstance(citations, list):
            used = len(citations) > 0
        elif tool_calls is not None:
            try:
                used = bool(tool_calls)
            except Exception:  # noqa: BLE001
                used = None
        else:
            used = None
        parsed.tool_used = used
        parsed.tool_trace = {
            "search_parameters": {"sources": ["web", "x"], "mode": "auto"},
            "citations_count": len(citations) if isinstance(citations, list) else None,
            "num_sources_used": num_sources_used,
            "tool_calls_count": len(tool_calls) if hasattr(tool_calls, "__len__") else None,
        }
        return parsed
