"""Read-only preparation; this module cannot dispatch model inference or searches."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from common.dataset.io import export_inputs, read_json, read_jsonl


class ConnectionStatus(StrEnum):
    PARTIAL_TEXT = "PARTIAL_TEXT"
    CONTRACT_BLOCKED = "CONTRACT_BLOCKED"


class BudgetStatus(StrEnum):
    PASS = "PASS"
    EXCEEDED = "EXCEEDED"
    UNVERIFIED = "UNVERIFIED"


class MetadataStatus(StrEnum):
    OBSERVED = "OBSERVED"
    UNVERIFIED = "UNVERIFIED"


class ProposalStatus(StrEnum):
    PROPOSED_NOT_APPROVED = "PROPOSED_NOT_APPROVED"


def collect_qwen_metadata(base_url: str, model: str, timeout_seconds: float = 10) -> dict[str, Any]:
    endpoint = urlsplit(base_url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Only the explicitly local metadata server is permitted")
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in {"", "/"}:
        raise ValueError("A local metadata origin without credentials or extra path is required")
    responses: dict[str, Any] = {}
    for path, payload in (("/api/version", None), ("/api/tags", None),
                          ("/api/ps", None), ("/api/show", {"model": model, "verbose": False})):
        started = perf_counter()
        request = Request(base_url.rstrip("/") + path,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("Metadata exceeds the inspection size limit")
            document = json.loads(raw)
            responses[path] = {"status": MetadataStatus.OBSERVED.value, "method": request.get_method(),
                               "duration_ms": (perf_counter() - started) * 1000,
                               "response_sha256": hashlib.sha256(raw).hexdigest(),
                               "response": {key: value for key, value in document.items() if key != "modelfile"}}
        except (OSError, ValueError) as exception:
            responses[path] = {"status": MetadataStatus.UNVERIFIED.value, "error_type": type(exception).__name__,
                               "duration_ms": (perf_counter() - started) * 1000}
    return {"captured_at": datetime.now(timezone.utc).isoformat(), "base_url": base_url,
            "requested_model": model, "metadata_only": True, "inference_calls": 0,
            "responses": responses}


def case_connections(root: Path) -> list[dict[str, Any]]:
    cases = read_jsonl(root / "generated/golden.jsonl")
    corpus = {place["id"]: place for place in read_json(root / "generated/corpus.json")}
    exported = {row["case_id"]: row for row in export_inputs(cases, corpus)}
    return [_case_connection(case, exported[case["case_id"]]) for case in cases]


def _case_connection(case: dict[str, Any], exported: dict[str, Any]) -> dict[str, Any]:
    supplied = case["input"]
    expected = case["expectations"]
    required = [call["name"] for call in expected["tool_call"]["required_calls"]]
    conditions = supplied.get("conditions") or {}
    unsupported = ["persona_not_configurable_in_current_conversation_api", "request_time_not_forwarded_as_clock"]
    mapped_or_separately_reported = {"query", "messages", "conversationId", "request_time", "conditions",
                                    "candidate_place_ids", "provided_contexts", "persona", "current_plan", "memory_sources"}
    unsupported.extend("unmapped_input:" + key for key in supplied if key not in mapped_or_separately_reported)
    unsupported.extend("unmapped_condition:" + key for key, value in conditions.items()
                       if value not in (None, [], "", {}) and key != "conversation")
    if supplied.get("provided_contexts"):
        unsupported.append("provided_contexts_have_no_authenticated_tool_result_input")
    if supplied.get("candidate_place_ids"):
        unsupported.append("candidate_fixture_not_server_search_corpus")
    if supplied.get("current_plan"):
        unsupported.append("current_plan_not_in_conversation_request")
    if expected.get("memory") is not None or supplied.get("memory_sources"):
        unsupported.append("memory_source_and_state_tools_unimplemented")
    if expected.get("state") is not None:
        unsupported.append("before_after_state_observations_unavailable")
    if "search_places" in required:
        unsupported.extend(["search_requires_complete_planning_request_and_circle_area",
                            "native_query_limit_schema_differs_from_frozen_search_schema"])
    if expected.get("plan") is not None or "create_plan" in required:
        unsupported.extend(["generate_plan_job_draft_is_not_create_plan_preview",
                            "trusted_route_matrix_not_connected"])
    unsupported.extend("unregistered_tool:" + name for name in required
                       if name not in {"search_places", "generate_plan", "get_planning_job"})
    partial_text = (case["expected_response_type"] == "TEXT" and not required
                    and expected.get("memory") is None and expected.get("state") is None)
    supported = ["api_query_and_user_assistant_history_transport", "server_conversation_id"]
    if partial_text:
        supported.extend(["text_response_type_after_observed_completion", "no_tool_call_after_observed_completion",
                          "explanation_on_actually_delivered_evidence_only"])
    return {
        "case_id": case["case_id"], "split": case["split"], "input_sha256": exported["input_sha256"],
        "expected_response_type": case["expected_response_type"], "required_tools": required,
        "connection": ConnectionStatus.PARTIAL_TEXT.value if partial_text else ConnectionStatus.CONTRACT_BLOCKED.value,
        "full_frozen_case_compatible": False, "supported_partial_observations": supported,
        "unsupported": unsupported,
        "minimal_api_request": {"message": supplied["query"], "history": [
            {"role": message["role"].upper(), "content": message["content"]}
            for message in supplied.get("messages") or []],
                                "planningRequest": None},
        "conversation_id": supplied["conversationId"],
        "budget_scope": "actual initial API query/history; unsupported frozen fields are NOT claimed as delivered",
        "pilot_candidate": partial_text and not supplied.get("provided_contexts") and case["split"] == "development",
    }


def budget_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {status.value: sum(row["status"] == status.value for row in rows) for status in BudgetStatus}


def propose_pilot(connections: list[dict[str, Any]], budgets: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = sorted((row for row in connections if row["pilot_candidate"]), key=lambda row: row["case_id"])
    proposed = candidates[:2]
    budget_index = {row["case_id"]: row for row in budgets if row.get("scope") == "INITIAL_API_REQUEST"}
    ready = bool(proposed) and all(budget_index.get(row["case_id"], {}).get("status") == BudgetStatus.PASS for row in proposed)
    return {
        "status": ProposalStatus.PROPOSED_NOT_APPROVED.value, "approved": False, "executed": False,
        "target_app_model": "qwen3:8b", "app_gpt_model": None,
        "judge_model_configured_only": "gpt-4.1-mini", "judge_calls_proposed": 0,
        "case_ids": [row["case_id"] for row in proposed], "selection": "first two sorted development text-only candidates",
        "repetitions_proposed": 1, "concurrency_proposed": 1,
        "current_budget_ready": ready, "inference_calls_authorized_now": 0,
        "conditional_pilot_inference_cap": len(proposed),
        "conditional_pilot_expected_tools": [], "conditional_pilot_job_calls": 0,
        "default_server_max_chat_calls_per_request": 6, "default_server_max_async_plan_calls_per_turn": 1,
        "default_server_total_inference_cap_per_request_including_generate_plan": 7,
        "server_default_is_not_the_proposed_global_cap": True,
        "paid_api_cost_usd_proposed": 0, "local_compute_cost": "not measured; local inference is not zero compute cost",
        "inference_latency_observed_ms": None, "latency_planning_assumption_seconds_per_case": [30, 120],
        "latency_assumption_not_a_measurement": True, "job_timeout_is_not_cancellation": True,
        "stop_conditions": ["user approval absent", "budget is EXCEEDED or UNVERIFIED", "metadata model/template drift",
                            "unexpected tool call before any tool execution", "global inference cap reached",
                            "recording failure or missing usage", "timeout; do not retry or claim cancellation",
                            "any search, persistence, planning job or production side effect would be required"],
        "required_before_execution": ["approval of these explicit IDs/repetition/caps",
                                      "budget blockers resolved without silently truncating evidence",
                                      "one-call stop-before-tool runner and hard global cap must be verified",
                                      "persona/frozen-input gaps excluded from claimed quality coverage"],
    }
