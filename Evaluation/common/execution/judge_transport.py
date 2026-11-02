"""One bounded completion per explicit pass, with SDK and application retries disabled."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from common.execution.control import ExecutionBlocked, Operation, RunControl, RunMode


@asynccontextmanager
async def judge_client(control: RunControl, *, api_key: str | None = None) -> AsyncIterator[Any]:
    if control.settings.mode == RunMode.MOCK:
        yield None
        return
    import httpx
    from openai import AsyncOpenAI
    endpoint = control.settings.parameter("judge_base_url")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ExecutionBlocked("LIVE judge requires an explicit HTTPS endpoint without embedded credentials")
    async with AsyncOpenAI(
        api_key=api_key,
        base_url=endpoint,
        max_retries=0,
        timeout=control.settings.timeout_seconds,
        http_client=httpx.AsyncClient(timeout=control.settings.timeout_seconds, trust_env=False, follow_redirects=False),
    ) as client:
        yield client


async def bounded_completion(
    control: RunControl,
    case_id: str,
    request: dict[str, Any],
    *,
    client: Any,
) -> dict[str, Any]:
    if request.get("model") != control.settings.model or request.get("max_completion_tokens") != control.settings.max_output_tokens:
        raise ExecutionBlocked("Judge model and output reservation must match the explicit configuration")
    async def dispatch() -> dict[str, Any]:
        response = await client.chat.completions.create(**request)
        return {**response.model_dump(mode="json"), "provider_http_request_id": getattr(response, "_request_id", None)}
    return await control.execute(
        Operation.JUDGE,
        case_id,
        completion_observation_request(control, request),
        dispatch,
    )


def completion_observation_request(control: RunControl, request: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "openai",
        "base_url": control.settings.parameters.get("judge_base_url"),
        "arguments": request,
    }


def completion_document(control: RunControl, completion: dict[str, Any]) -> dict[str, Any]:
    try:
        choice = completion["choices"][0]
        message = choice["message"]
        if choice["finish_reason"] != "stop" or message.get("refusal") or not message.get("content"):
            raise ValueError("Judge response did not finish normally")
        return json.loads(message["content"])
    except (ValueError, KeyError, TypeError, IndexError) as exception:
        control.reject_result(type(exception).__name__)
        raise


def usage_totals(runs: list[dict[str, Any]], mode: RunMode) -> dict[str, Any]:
    def summarize_field(name: str) -> dict[str, int | None]:
        observed = [run["usage"][name] for run in runs if mode == RunMode.LIVE and type((run.get("usage") or {}).get(name)) is int]
        return {"known_sum": sum(observed) if observed else None, "observed_count": len(observed), "missing_count": len(runs) - len(observed)}
    return {name: summarize_field(name) for name in ("prompt_tokens", "completion_tokens", "total_tokens")}
