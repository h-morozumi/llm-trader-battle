from __future__ import annotations

import os

from xai_sdk import Client as XaiClient
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


def _create_agent_tools() -> list:
    """Create Agent Tools for web search and X search."""
    return [
        chat_pb2.Tool(web_search=chat_pb2.WebSearch()),
        chat_pb2.Tool(x_search=chat_pb2.XSearch()),
    ]


def _extract_tool_trace(resp) -> tuple[bool | None, dict | None]:
    """Extract tool usage information from the response."""
    # Check for tool calls in response
    tool_calls = getattr(resp, "tool_calls", None)
    citations = getattr(resp, "citations", None)
    usage = getattr(resp, "usage", None)

    # Count search-related outputs
    web_search_count = 0
    x_search_count = 0
    if tool_calls:
        for tc in tool_calls:
            tc_type = getattr(tc, "type", None) or ""
            if "web" in str(tc_type).lower():
                web_search_count += 1
            if "x_search" in str(tc_type).lower() or "twitter" in str(tc_type).lower():
                x_search_count += 1

    num_sources_used = getattr(usage, "num_sources_used", None) if usage else None

    # Determine if tools were used
    used: bool | None
    if isinstance(num_sources_used, int):
        used = num_sources_used > 0
    elif tool_calls:
        used = len(tool_calls) > 0
    elif isinstance(citations, list):
        used = len(citations) > 0
    else:
        used = None

    trace = {
        "tools_configured": ["web_search", "x_search"],
        "tool_choice": "auto",
        "web_search_calls": web_search_count,
        "x_search_calls": x_search_count,
        "citations_count": len(citations) if isinstance(citations, list) else None,
        "num_sources_used": num_sources_used,
        "tool_calls_count": len(tool_calls) if tool_calls else 0,
    }
    return used, trace


class GrokOpenAIClient(LlmClient):
    def __init__(self) -> None:
        self._client = _build_client()
        self._model = os.environ.get("GROK_MODEL", "grok-3")

    def generate(self, req: PickRequest) -> PickResponse:
        prompt = build_prompt(req)

        # Build messages
        messages = [
            chat_pb2.Message(
                role=chat_pb2.MessageRole.ROLE_USER,
                content=[chat_pb2.Content(text=prompt)],
            )
        ]

        # Create chat with Agent Tools API (web_search and x_search)
        chat = self._client.chat.create(
            model=self._model,
            messages=messages,
            max_tokens=1024,
            response_format="json_object",
            tools=_create_agent_tools(),
            tool_choice="auto",
        )

        # Execute and get response
        resp = chat.sample()

        # Parse the response content
        parsed = parse_picks_json(resp.content)

        # Extract tool usage trace
        used, trace = _extract_tool_trace(resp)
        parsed.tool_used = used
        parsed.tool_trace = trace

        return parsed
