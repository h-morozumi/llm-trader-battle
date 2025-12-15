from __future__ import annotations

import asyncio
import json
import os

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock, query

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


async def _run_claude(prompt: str, model: str) -> tuple[str, dict]:
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
    error_message: str | None = None
    tool_uses: list[dict] = []
    tool_results: list[dict] = []
    # IMPORTANT: don't raise inside the async generator loop.
    # Some SDK versions use AnyIO cancel scopes that can emit noisy errors
    # if the generator is aborted mid-iteration. Capture the error and break,
    # allowing the generator to close cleanly within this task.
    async for message in query(prompt=prompt, options=opts):
        if isinstance(message, AssistantMessage):
            parts: list[str] = []
            for block in message.content:
                if isinstance(block, TextBlock) and block.text:
                    parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_uses.append(
                        {
                            "name": getattr(block, "name", None),
                            "id": getattr(block, "id", None),
                            "input": getattr(block, "input", None),
                        }
                    )
                elif isinstance(block, ToolResultBlock):
                    tool_results.append(
                        {
                            "tool_use_id": getattr(block, "tool_use_id", None),
                            "is_error": getattr(block, "is_error", None),
                            "content": getattr(block, "content", None),
                        }
                    )
            if parts:
                last_text = "".join(parts)
        elif isinstance(message, ResultMessage):
            if message.is_error:
                error_message = message.result or "Claude agent returned an error"
                break
            if message.structured_output is not None:
                last_structured = message.structured_output
            if isinstance(message.result, str) and message.result.strip():
                last_result = message.result

    tool_trace = {
        "allowed_tools": ["WebSearch", "WebFetch"],
        "tool_uses": tool_uses,
        "tool_results": tool_results,
        "tool_use_count": len(tool_uses),
        "tool_names": sorted({t.get("name") for t in tool_uses if t.get("name")}),
    }

    if error_message:
        raise RuntimeError(error_message)

    if isinstance(last_structured, dict) and last_structured:
        return json.dumps(last_structured, ensure_ascii=False), tool_trace
    if last_text and last_text.strip():
        return last_text, tool_trace
    if last_result and last_result.strip():
        return last_result, tool_trace
    raise RuntimeError("Claude agent returned no text content")


class ClaudeClient(LlmClient):
    def __init__(self) -> None:
        model = _get_model()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._model = model

    def generate(self, req: PickRequest) -> PickResponse:
        prompt = build_prompt(req)
        try:
            text, tool_trace = asyncio.run(_run_claude(prompt, self._model))
        except RuntimeError as e:
            raise RuntimeError(f"Claude ({self._model}) failed: {e}") from e
        parsed = parse_picks_json(text)
        parsed.tool_trace = tool_trace
        parsed.tool_used = bool(tool_trace.get("tool_uses"))
        return parsed
