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
        return parse_picks_json(resp.content)
