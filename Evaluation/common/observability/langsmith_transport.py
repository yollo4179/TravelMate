"""Count individual LangSmith HTTP requests; no SDK batching, retries, or polling."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import json
import math
import os
from typing import Any, AsyncIterator
from urllib.parse import urlparse
import uuid

from common.dataset.io import canonical_digest
from common.execution.control import ExecutionBlocked, Operation, RunControl, RunMode


class LangSmithTransport:
    def __init__(self, control: RunControl, client: Any = None, api_key: str | None = None) -> None:
        self.control = control
        self.client = client
        self.api_key = api_key
        self.base_url = control.settings.parameter("langsmith_api_url").rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ExecutionBlocked("An explicit HTTPS LangSmith endpoint without embedded credentials is required")

    async def request(
        self,
        operation: Operation,
        case_id: str,
        method: str,
        route: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed_read = operation == Operation.OBSERVATION_READ and (
            (method == "POST" and route == "/runs/query")
            or (method == "GET" and (route.startswith("/runs/") or route.startswith("/feedback/")))
        )
        allowed_write = operation == Operation.PUBLISH and method == "POST" and route in ("/runs", "/feedback")
        if not (allowed_read or allowed_write):
            raise ExecutionBlocked("Only scoped read requests and create-only run/feedback writes are supported")
        request = {"method": method, "url": self.base_url + route, "body": payload}
        async def dispatch() -> dict[str, Any]:
            response = await self.client.request(
                method,
                request["url"],
                json=payload,
                headers={"x-api-key": self.api_key},
            )
            return {"status_code": response.status_code, "raw_body": response.text, "request_id": response.headers.get("x-request-id")}
        response = await self.control.execute(operation, case_id, request, dispatch)
        try:
            if not 200 <= response["status_code"] < 300:
                raise ValueError("LangSmith HTTP request failed; no retry or alternate target is attempted")
            return json.loads(response["raw_body"]) if response["raw_body"].strip() else {}
        except (ValueError, KeyError, TypeError) as exception:
            self.control.reject_result(type(exception).__name__)
            raise


@asynccontextmanager
async def langsmith_transport(control: RunControl, api_key_env: str) -> AsyncIterator[LangSmithTransport]:
    if control.settings.mode == RunMode.MOCK:
        yield LangSmithTransport(control)
        return
    import httpx
    api_key = os.environ[api_key_env]
    async with httpx.AsyncClient(timeout=control.settings.timeout_seconds, trust_env=False, follow_redirects=False) as client:
        yield LangSmithTransport(control, client, api_key)


async def publish_artifact(
    control: RunControl,
    transport: LangSmithTransport,
    *,
    name: str,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    control.settings.require_scope(artifact["case_ids"])
    purpose = control.settings.parameter("publication_purpose")
    if purpose not in ("verified_search_quality", "archive_legacy_report"):
        raise ExecutionBlocked("Publication purpose must distinguish verified search quality from historical reports")
    if control.settings.mode == RunMode.LIVE and purpose == "verified_search_quality" and artifact.get("quality_status") != "verified_search_observations":
        raise ExecutionBlocked("Unobserved, MOCK, failed or incomplete results cannot be published as measured quality")
    if purpose == "archive_legacy_report" and artifact.get("quality_status") != "legacy_report_only":
        raise ExecutionBlocked("Historical publication requires a separately identified legacy report")
    feedback_names = control.settings.parameter("feedback_metrics")
    if not isinstance(feedback_names, list) or len(feedback_names) != len(set(feedback_names)):
        raise ValueError("Feedback metric names must be explicitly selected and unique")
    if purpose == "archive_legacy_report" and feedback_names:
        raise ExecutionBlocked("Legacy reports cannot create verified-quality feedback")
    values = artifact.get("metrics") or {}
    if any(name not in values or type(values[name]) not in (int, float) or not math.isfinite(values[name]) for name in feedback_names):
        raise ExecutionBlocked("Missing or nonnumeric metrics cannot become successful numeric feedback")
    control.settings.require_capacity(Operation.PUBLISH, 1 + len(feedback_names))
    control.settings.require_capacity(Operation.OBSERVATION_READ, 1 + len(feedback_names))
    run_id = str(uuid.UUID(control.settings.parameter("run_id")))
    project_name = control.settings.parameter("project_name")
    project_id = str(uuid.UUID(control.settings.parameter("project_id")))
    if not isinstance(project_name, str) or not project_name.strip():
        raise ValueError("An explicit target project name is required")
    identifier = control.settings.case_ids[0]
    timestamp = control.settings.parameter("publication_timestamp")
    if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp).tzinfo is None:
        raise ValueError("Publication timestamp must be explicitly configured with its timezone")
    payload = {
        "id": run_id, "name": name, "run_type": "chain", "session_name": project_name,
        "start_time": timestamp, "end_time": timestamp,
        "inputs": {"case_ids": list(control.settings.case_ids), "source_sha256": artifact["source_sha256"], "publication_purpose": purpose},
        "outputs": artifact,
        "tags": [purpose, "MOCK" if control.settings.mode == RunMode.MOCK else "LIVE"],
    }
    await transport.request(Operation.PUBLISH, identifier, "POST", "/runs", payload)
    for metric in feedback_names:
        feedback_payload = {
            "id": str(uuid.uuid5(uuid.UUID(run_id), metric)),
            "run_id": run_id,
            "key": metric,
            "score": values[metric],
            "feedback_source": {
                "type": "api",
                "metadata": {"source_sha256": canonical_digest(artifact["source_sha256"])},
            },
        }
        await transport.request(
            Operation.PUBLISH,
            identifier,
            "POST",
            "/feedback",
            feedback_payload,
        )
    saved = await transport.request(Operation.OBSERVATION_READ, identifier, "GET", "/runs/" + run_id)
    if saved.get("id") != run_id or saved.get("outputs") != artifact or saved.get("session_id") != project_id:
        control.reject_result("PublicationReadbackMismatch")
        raise ValueError("Publication readback is missing or differs from the exact submitted artifact")
    for metric in feedback_names:
        feedback_id = str(uuid.uuid5(uuid.UUID(run_id), metric))
        feedback = await transport.request(Operation.OBSERVATION_READ, identifier, "GET", "/feedback/" + feedback_id)
        if feedback.get("id") != feedback_id or feedback.get("run_id") != run_id or feedback.get("key") != metric or feedback.get("score") != values[metric]:
            control.reject_result("FeedbackReadbackMismatch")
            raise ValueError("Feedback readback differs from the submitted metric")
    return {
        **control.summary(),
        "status": "mock_regression_only" if control.settings.mode == RunMode.MOCK else "published_and_read_back",
        "run_id": run_id,
        "quality_status": artifact["quality_status"],
        "feedback_submitted_count": len(feedback_names),
        "feedback_readback_verified": control.settings.mode == RunMode.LIVE,
        "publication_timestamp_source": "explicit_configuration_not_search_or_model_latency",
    }
