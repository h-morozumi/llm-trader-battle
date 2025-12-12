from __future__ import annotations

import asyncio
import json
import os

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from .base import LlmClient, PickRequest, PickResponse, build_prompt, parse_picks_json


def _get_model() -> str:
    return os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")


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


async def _run_claude(prompt: str, model: str) -> str:
    opts = ClaudeAgentOptions(
        model=model,
        # Enable Claude Code tool preset, then explicitly allow only the tools we want.
        # WebSearch: search the web
        # WebFetch: fetch a URL from the web
        tools={"type": "preset", "preset": "claude_code"},
        allowed_tools=["WebSearch", "WebFetch"],
        # Non-interactive execution: avoid permission prompts stopping the run.
        permission_mode="bypassPermissions",
        # Encourage strict JSON output; when supported, the SDK surfaces it as structured_output.
        output_format={"type": "json_schema", "schema": _response_schema()},
        setting_sources=[],  # avoid loading local settings
    )

    last_text: str | None = None
    last_result: str | None = None
    last_structured: object | None = None
    async for message in query(prompt=prompt, options=opts):
        if isinstance(message, AssistantMessage):
            parts: list[str] = []
            for block in message.content:
                if isinstance(block, TextBlock) and block.text:
                    parts.append(block.text)
            if parts:
                last_text = "".join(parts)
        elif isinstance(message, ResultMessage):
            if message.is_error:
                raise RuntimeError(message.result or "Claude agent returned an error")
            if message.structured_output is not None:
                last_structured = message.structured_output
            if isinstance(message.result, str) and message.result.strip():
                last_result = message.result

    if isinstance(last_structured, dict) and last_structured:
        return json.dumps(last_structured, ensure_ascii=False)
    if last_text and last_text.strip():
        return last_text
    if last_result and last_result.strip():
        return last_result
    raise RuntimeError("Claude agent returned no text content")


class ClaudeClient(LlmClient):
    def __init__(self) -> None:
        model = _get_model()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._model = model

    def generate(self, req: PickRequest) -> PickResponse:
        prompt = build_prompt(req)
        text = asyncio.run(_run_claude(prompt, self._model))
        return parse_picks_json(text)
