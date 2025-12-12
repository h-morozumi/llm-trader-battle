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
        return parse_picks_json(resp.text)
