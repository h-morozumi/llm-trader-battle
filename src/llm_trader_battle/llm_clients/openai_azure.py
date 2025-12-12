from __future__ import annotations

import inspect
import os

from openai import OpenAI

from .base import LlmClient, PickRequest, PickResponse, build_prompt, parse_picks_json


def _build_client() -> OpenAI:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT")
    if not all([endpoint, api_key, api_version, deployment]):
        raise RuntimeError("Azure OpenAI env vars are not fully set")
    # Azure Responses API uses deployment name as model and api-version query
    return OpenAI(
        api_key=api_key,
        base_url=f"{endpoint}/openai",
        default_query={"api-version": api_version},
        default_headers={"api-key": api_key},
    )


def _safe_model_dump(obj):
    fn = getattr(obj, "model_dump", None)
    if callable(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return None
    return None


def _response_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "symbol": {"type": "string"},
                        "reason": {"type": "string"},
                        "method": {"type": "string"},
                    },
                    "required": ["symbol", "reason", "method"],
                },
                "minItems": 1,
            }
        },
        "required": ["picks"],
    }


def _extract_web_search_trace(resp) -> tuple[bool | None, dict | None]:
    dump = _safe_model_dump(resp)
    if not isinstance(dump, dict):
        return None, None

    output = dump.get("output")
    output_types: list[str] = []
    web_items: list[dict] = []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if isinstance(t, str):
                output_types.append(t)
            if isinstance(t, str) and t.startswith("web_search"):
                web_items.append({"type": t, **{k: item.get(k) for k in ("id", "status") if k in item}})

    used = bool(web_items)
    trace: dict[str, object] = {
        "tools_configured": [{"type": "web_search", "search_context_size": "low"}],
        "output_item_types": output_types,
        "web_search_items": web_items,
        "web_search_item_count": len(web_items),
    }
    return used, trace


class AzureOpenAIClient(LlmClient):
    def __init__(self) -> None:
        self._client = _build_client()
        self._deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT", "")

    def generate(self, req: PickRequest) -> PickResponse:
        prompt = build_prompt(req)
        schema = _response_schema()
        # OpenAI Python SDK has changed how Structured Outputs is specified for the
        # Responses API across versions/providers.
        text_format = {
            "type": "json_schema",
            "name": "weekly_picks",
            "schema": schema,
            "strict": True,
        }
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "weekly_picks",
                "schema": schema,
                "strict": True,
            },
        }

        base_kwargs = {
            "model": self._deployment,
            "instructions": "Return only JSON matching the schema. No prose, no markdown.",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "max_output_tokens": 2048,
            "reasoning": None,
            "tools": [{"type": "web_search", "search_context_size": "low"}],
        }

        # Prefer the modern `text.format` if available; fall back to `response_format`.
        try:
            params = inspect.signature(self._client.responses.create).parameters
        except Exception:  # noqa: BLE001
            params = {}

        if "text" in params:
            resp = self._client.responses.create(**base_kwargs, text={"format": text_format})
        elif "response_format" in params:
            resp = self._client.responses.create(**base_kwargs, response_format=response_format)
        else:
            # Last resort: try `text` then fall back.
            try:
                resp = self._client.responses.create(**base_kwargs, text={"format": text_format})
            except TypeError:
                resp = self._client.responses.create(**base_kwargs, response_format=response_format)
        if hasattr(resp, "output_text") and resp.output_text:
            text = resp.output_text
        else:
            # Fallback parsing for Responses output array
            output = getattr(resp, "output", None) or []
            if output and getattr(output[0], "content", None):
                text = output[0].content[0].text  # type: ignore[index]
            else:
                # Some deployments may return choices-style structure
                choices = getattr(resp, "choices", None) or []
                if choices and getattr(choices[0], "message", None):
                    parts = getattr(choices[0].message, "content", None) or []
                    if parts:
                        text = getattr(parts[0], "text", None) or getattr(parts[0], "value", None)
                    else:
                        text = getattr(choices[0].message, "content", "")
                else:
                    try:
                        raw = resp.model_dump()
                    except Exception:  # noqa: BLE001
                        raw = str(resp)
                    raise ValueError(f"No text output from Azure Responses: {raw}")
        parsed = parse_picks_json(text)
        used, trace = _extract_web_search_trace(resp)
        parsed.tool_used = used
        parsed.tool_trace = trace
        return parsed
