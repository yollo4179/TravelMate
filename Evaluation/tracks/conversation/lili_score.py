"""Scores a LILI_ROUTER_V1 turn: LiLi's branch decision, the server-run tool, and the job result she queued."""
from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from common.dataset.io import canonical_digest

BRANCH_TOOLS = {
    "CHAT": [],
    "CLARIFY": [],
    "SEARCH_PLACES": ["search_places"],
    "GENERATE_PLAN": ["generate_plan"],
    "GET_PLANNING_JOB": ["get_planning_job"],
}
QUERY_BRANCHES = {"SEARCH_PLACES", "GENERATE_PLAN"}
LEGACY_ONLY_CHECKS = {"response_type", "message_source", "intent_type", "array_result_preserved"}
ROUTER_LINE_CRITERION = {
    "id": "router_line_no_place_facts",
    "guidance": "LiLi의 첫 대사는 장소 근거를 받기 전에 쓴 것이므로 반응과 예고만 하고 장소의 특징·위치·주차·운영시간 같은 사실을 말하지 않는다.",
}


def _payloads(selected: list[dict[str, Any]], event: str, phase: str | None = None) -> list[dict[str, Any]]:
    return [item["payload"] for item in selected if item["event"] == event and (phase is None or item.get("phase") == phase)]


def _valid(schema: dict[str, Any], value: Any) -> bool:
    return not list(Draft202012Validator(schema).iter_errors(value))


def _decision(route: dict[str, Any] | None) -> dict[str, Any] | None:
    try:
        return json.loads(route["content"]) if route and isinstance(route.get("content"), str) else None
    except ValueError:
        return None


def _sources(preparations: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    sources: dict[str, dict[str, Any]] = {}
    supplied = []
    for model_data in [item.get("modelData") or {} for item in preparations]:
        for candidate in model_data.get("candidates", []):
            for evidence in candidate.get("selectedEvidence", []):
                original = evidence.get("original", {})
                entry = {"placeId": candidate["placeId"], "sourceId": original.get("source_id"), "text": original.get("chunk_text")}
                sources[evidence["evidenceId"]] = entry
                supplied.append({"evidenceId": evidence["evidenceId"], **entry})
    return sources, supplied


def _job_checks(
    record: dict[str, Any],
    expected: dict[str, Any],
    decision: dict[str, Any],
    job_preparations: list[dict[str, Any]],
    contract: dict[str, Any],
) -> tuple[dict[str, bool | None], dict[str, Any], list[dict[str, Any]]]:
    job = record.get("recommendation_job") or {}
    result = job.get("result") or {}
    checks: dict[str, bool | None] = {
        "job_completed": job.get("status") == "SUCCEEDED",
        "job_single_retrieval": len(job_preparations) == 1,
        "job_query_is_lili_query": len(job_preparations) == 1 and job_preparations[0].get("query") == decision.get("search_query"),
        "job_result_places": result.get("type") == "PLACES",
        "job_result_by_lili": result.get("messageSource") == "LLM" and result.get("termination") == "COMPLETED",
    }
    cuts = result.get("dialogue") or []
    cut_schema = contract.get("lili", {}).get("recommendation_schema", {}).get("properties", {}).get("dialogue")
    checks["job_dialogue_cuts"] = _valid(cut_schema, cuts) if cut_schema else None
    sources, supplied = _sources(job_preparations)
    citations = result.get("citations") or []
    checks["job_citation_membership"] = all(
        isinstance(citation, dict) and (source := sources.get(citation.get("evidenceId"))) is not None
        and source["placeId"] == citation.get("placeId") and source["sourceId"] == citation.get("sourceId")
        and isinstance(source["text"], str) and citation.get("quote", "") in source["text"] for citation in citations)
    if expected.get("citations") == "REQUIRED":
        checks["job_citations_required"] = bool(citations)
    return checks, result, supplied


def score_lili_case(case: dict[str, Any], record: dict[str, Any], selected: list[dict[str, Any]],
                    contract: dict[str, Any], base_checks: dict[str, bool | None], trace_error: str | None) -> dict[str, Any]:
    expected = case["expected"]
    native = record.get("native_response") if isinstance(record.get("native_response"), dict) else {}
    # Legacy checks assume pre-retrieved places in the chat turn; LiLi's turn is judged by its own rules below.
    checks = {name: value for name, value in base_checks.items() if name not in LEGACY_ONLY_CHECKS}
    routes = _payloads(selected, "ROUTE")
    route = routes[0] if len(routes) == 1 else None
    decision = _decision(route) or {}
    lili = contract.get("lili", {})
    branch = decision.get("branch")
    checks["route_observed"] = route is not None and route.get("stage") == "ROUTER"
    checks["route_schema"] = _valid(lili["router_schema"], decision) if route and "router_schema" in lili else None
    checks["lili_branch"] = branch == expected.get("lili_branch")
    checks["search_query_present"] = bool((decision.get("search_query") or "").strip()) if branch in QUERY_BRANCHES else None
    checks["no_evidence_before_lili"] = not _payloads(selected, "EVIDENCE_PREPARATION", "CONVERSATION")
    tool_events = [item for item in _payloads(selected, "TOOL_RESULT", "CONVERSATION")]
    executed = [item.get("result", {}) for item in tool_events]
    checks["tool_selection"] = [item.get("name") for item in executed] == BRANCH_TOOLS.get(expected.get("lili_branch"), [])
    checks["tools_run_by_server"] = all(item.get("initiator") == "LILI" for item in tool_events)
    arguments = [json.loads(item.get("arguments") or "{}") for item in executed]
    if expected.get("lili_branch") == "GET_PLANNING_JOB":
        checks["tool_arguments"] = len(arguments) == 1 and bool(arguments[0].get("job_id")) and arguments[0]["job_id"] in case["api_request"]["message"]
    elif expected.get("lili_branch") == "GENERATE_PLAN":
        checks["tool_arguments"] = arguments == [{}]
    elif expected.get("lili_branch") == "SEARCH_PLACES":
        checks["tool_arguments"] = len(arguments) == 1 and arguments[0].get("query") == decision.get("search_query")
    checks["intent_type"] = native.get("intent") == expected.get("intent")
    checks["message_source"] = native.get("messageSource") == "LLM"
    checks["dialogue_present"] = bool(native.get("dialogue")) and native.get("message") == native["dialogue"][0].get("text")
    expected_type = {"SEARCH_PLACES": "RECOMMENDATION_JOB", "GENERATE_PLAN": "PLANNING_JOB", "GET_PLANNING_JOB": "PLANNING_JOB"}
    checks["response_type"] = native.get("type") == expected_type.get(expected.get("lili_branch"), "TEXT") or (
        expected.get("lili_branch") == "GET_PLANNING_JOB" and native.get("type") in {"PLANNING_JOB", "DRAFT"})
    checks["choices_only_when_clarifying"] = bool(native.get("choices")) == (branch == "CLARIFY") if branch else None
    citations: list[dict[str, Any]] = []
    supplied: list[dict[str, Any]] = []
    job_preparations = _payloads(selected, "EVIDENCE_PREPARATION", "RECOMMENDATION_GENERATION")
    if expected.get("lili_branch") == "SEARCH_PLACES":
        job_checks, result, supplied = _job_checks(record, expected, decision, job_preparations, contract)
        checks.update(job_checks)
        citations = result.get("citations") or []
    model_calls = [item for item in _payloads(selected, "MODEL_CALL") if item.get("stage") == "FINISHED"]
    checks["provider_identity"] = all(call.get("provider") == contract["provider"] and call.get("model") == contract["model"]
                                      for call in model_calls) if model_calls else None
    automated = "failed" if any(value is False for value in checks.values()) else "not_assessed" if any(
        value is None for name, value in checks.items() if name in {"route_observed", "trace_binding", "lili_branch"}) else "passed"
    live = record.get("execution_mode") == "LIVE"
    follow_ups = [item for item in _payloads(selected, "MODEL_TURN") if item.get("stage") == "FOLLOW_UP"]
    job_turns = [item for item in _payloads(selected, "MODEL_TURN") if item.get("stage") == "RECOMMENDATION"]
    job = record.get("recommendation_job") or {}
    criteria = list(expected["semantic_criteria"])
    if branch in QUERY_BRANCHES:
        criteria.append(ROUTER_LINE_CRITERION)
    usage = [call.get("receipt", {}).get("usage") for call in model_calls]
    return {"case_id": case["case_id"], "input_sha256": case["input_sha256"], "automated_status": automated,
            "checks": checks, "not_applicable_checks": [name for name, value in checks.items() if value is None],
            "trace_error": trace_error, "lili_decision": decision,
            "response_text": " / ".join(cut.get("text", "") for cut in native.get("dialogue") or []) or native.get("message"),
            "job_response_text": " / ".join(cut.get("text", "") for cut in (job.get("result") or {}).get("dialogue") or []) or None,
            "citations": citations, "model_tool_calls": [], "supplied_evidence": supplied,
            "question": case["api_request"]["message"], "semantic_criteria": criteria,
            "acceptable_response_example": expected["message_example"], "semantic_status": "not_reviewed",
            "quality_observed": live and bool(model_calls) and all(call.get("status") == "SUCCEEDED" for call in model_calls),
            "plan_content": {"status": "not_applicable", "checks": {}, "route_time_verified": False, "opening_hours_verified": False},
            "observed_calls": {"model_calls": len(model_calls), "router_calls": len(routes), "follow_up_calls": len(follow_ups),
                               "recommendation_calls": len(job_turns), "server_tool_executions": len(tool_events),
                               "job_retrievals": len(job_preparations), "job_polls": record.get("recommendation_job_polls")},
            "latency_ms": {"conversation_http": record.get("duration_ms") if live else None,
                           "router": route.get("durationMs") if live and route else None,
                           "follow_up": [item.get("durationMs") for item in follow_ups] if live else None,
                           "tool_execution": [item.get("durationMs") for item in tool_events] if live else None,
                           "job_wait": record.get("recommendation_job_wait_ms") if live else None,
                           "job_pre_retrieval": job_preparations[0].get("durationMs") if live and len(job_preparations) == 1 else None,
                           "job_inference": [item.get("durationMs") for item in job_turns] if live else None},
            "observed_usage": usage if live else None,
            "quality_status": "mock_regression_only" if record.get("execution_mode") == "MOCK" else "semantic_review_required",
            "record_sha256": canonical_digest(record), "events_sha256": canonical_digest(selected)}
