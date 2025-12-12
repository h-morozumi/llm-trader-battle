from __future__ import annotations

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
        resp = self._client.responses.create(
            model=self._deployment,
            instructions="Return only JSON matching the schema. No prose, no markdown.",
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            max_output_tokens=2048,
            reasoning=None,
            tools=[{"type": "web_search", "search_context_size": "low"}],
        )
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
