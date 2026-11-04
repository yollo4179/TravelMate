"""Scores a LILI_ROUTER_V1 turn: LiLi's branch decision, the server-run tool, and the job result she queued."""
from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import Draft202012Validator

from common.dataset.io import canonical_digest
from tracks.conversation.plan_checks import draft_checks

BRANCH_TOOLS = {
    "CHAT": [],
    "CLARIFY": [],
    "SEARCH_PLACES": ["search_places"],
    "GENERATE_PLAN": ["generate_plan"],
    "GET_PLANNING_JOB": ["get_planning_job"],
}
QUERY_BRANCHES = {"SEARCH_PLACES", "GENERATE_PLAN"}
LEGACY_ONLY_CHECKS = {"response_type", "message_source", "intent_type", "array_result_preserved"}
DRAFT_COMPLETED = "DRAFT_COMPLETED"
ROUTER_LINE_CRITERION = {
    "id": "router_line_no_place_facts",
    "guidance": "LiLi의 첫 대사는 장소 근거를 받기 전에 쓴 것이므로 반응과 예고만 하고 장소의 특징·위치·주차·운영시간 같은 사실을 말하지 않는다.",
}
# What a user must never hear from LiLi: server codes (JOB_ID_NOT_FOUND, COUNT_UNAVAILABLE) and pipeline vocabulary.
# Lookarounds, not \b: Hangul counts as a word character, so "JOB_ID_NOT_FOUND라고" would slip past \b.
INTERNAL_CODE = re.compile(r"(?<![A-Za-z0-9_])[A-Z]{2,}(?:_[A-Z]{2,})+(?![A-Za-z0-9_])")
# Input field names such as requiredStops or selectedEvidence; a plan description said "requiredStops" to the user.
INTERNAL_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])[a-z]+(?:[A-Z][a-z0-9]*)+(?![A-Za-z0-9_])")
INTERNAL_TERMS = ("토큰", "예산", "LLM", "API", "evidence", "셀렉트", "selectedEvidence", "서버",
                  "QUEUED", "RUNNING", "SUCCEEDED", "FAILED")
PARENTHESIZED = re.compile(r"\([^)]*\)")


def _payloads(selected: list[dict[str, Any]], event: str, phase: str | None = None) -> list[dict[str, Any]]:
    return [item["payload"] for item in selected if item["event"] == event and (phase is None or item.get("phase") == phase)]


def _valid(schema: dict[str, Any], value: Any) -> bool:
    return not list(Draft202012Validator(schema).iter_errors(value))


def _decision(route: dict[str, Any] | None) -> dict[str, Any] | None:
    try:
        return json.loads(route["content"]) if route and isinstance(route.get("content"), str) else None
    except ValueError:
        return None


def _texts(dialogue: Any) -> list[str]:
    return [cut.get("text", "") for cut in dialogue if isinstance(cut, dict)] if isinstance(dialogue, list) else []


def internal_terms(texts: list[str]) -> list[str]:
    found = [match for text in texts for pattern in (INTERNAL_CODE, INTERNAL_IDENTIFIER) for match in pattern.findall(text)]
    return found + [term for term in INTERNAL_TERMS if any(term in text for text in texts)]


MIN_NAME_LENGTH = 2


def _spoken_names(name: str) -> set[str]:
    """How a catalog name is said aloud: "사직공원(서울)" → "사직공원", "서울 운현궁" → also "운현궁"."""
    base = PARENTHESIZED.sub("", name).strip()
    tokens = base.split()
    names = {base}
    if len(tokens) > 1:
        names.add(tokens[-1])
    return {spoken for spoken in names if len(spoken) >= MIN_NAME_LENGTH}


def unevidenced_places_named(texts: list[str], candidates: list[dict[str, Any]]) -> list[str]:
    spoken = " ".join(texts)
    grounded = sorted({variant for item in candidates if item.get("selectedEvidence")
                       for variant in _spoken_names(item.get("name") or "")}, key=len, reverse=True)
    # Remove grounded names first so "창경궁" inside a grounded "창경궁 홍화문" is not blamed on another candidate.
    for name in grounded:
        spoken = spoken.replace(name, " ")
    return sorted({variant for item in candidates if not item.get("selectedEvidence")
                   for variant in _spoken_names(item.get("name") or "") if variant in spoken})


def _prompt_candidates(prompt: str | None) -> list[dict[str, Any]]:
    """The plan prompt ends with the exact JSON the planner read; older runs did not record it."""
    if not prompt or "{" not in prompt:
        return []
    try:
        return json.loads(prompt[prompt.index("{"):]).get("candidates", [])
    except ValueError:
        return []


def _review_candidates(preparations: list[dict[str, Any]], plan_drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What each job step had about its candidates, so a reviewer can tell an uncited claim from an invented one."""
    steps = (("recommendation", [candidate for item in preparations for candidate in (item.get("modelData") or {}).get("candidates", [])]),
             ("plan", [candidate for item in plan_drafts for candidate in _prompt_candidates(item.get("prompt"))]))
    return [{"step": step, "placeId": candidate.get("placeId"), "name": candidate.get("name"),
             "evidenceAvailability": candidate.get("evidenceAvailability"), "description": candidate.get("description")}
            for step, candidates in steps for candidate in candidates]


def _draft_summary(draft: dict[str, Any]) -> dict[str, Any] | None:
    if not draft:
        return None
    context = draft.get("context") or {}
    return {"title": draft.get("title"), "description": draft.get("description"),
            "window": [context.get("startAt"), context.get("endAt")], "warnings": draft.get("warnings"),
            "pins": [{"placeId": pin.get("placeId"), "name": pin.get("name"), "stayMinutes": pin.get("stayMinutes"),
                      "explanation": pin.get("explanation")} for pin in draft.get("pins") or []]}


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


def _recommendation_checks(
    followed: dict[str, Any],
    expected: dict[str, Any],
    decision: dict[str, Any],
    job_preparations: list[dict[str, Any]],
    cut_schema: dict[str, Any] | None,
) -> tuple[dict[str, bool | None], dict[str, Any], list[dict[str, Any]]]:
    job = followed.get("job") or {}
    result = job.get("result") or {}
    checks: dict[str, bool | None] = {
        "job_completed": job.get("status") == "SUCCEEDED" and not followed.get("timed_out"),
        "job_single_retrieval": len(job_preparations) == 1,
        "job_query_is_lili_query": len(job_preparations) == 1 and job_preparations[0].get("query") == decision.get("search_query"),
        "job_result_places": result.get("type") == "PLACES",
        "job_result_by_lili": result.get("messageSource") == "LLM" and result.get("termination") == "COMPLETED",
    }
    checks["job_dialogue_cuts"] = _valid(cut_schema, result.get("dialogue") or []) if cut_schema else None
    sources, supplied = _sources(job_preparations)
    citations = result.get("citations") or []
    checks["job_citation_membership"] = all(
        isinstance(citation, dict) and (source := sources.get(citation.get("evidenceId"))) is not None
        and source["placeId"] == citation.get("placeId") and source["sourceId"] == citation.get("sourceId")
        and isinstance(source["text"], str) and citation.get("quote", "") in source["text"] for citation in citations)
    if expected.get("citations") == "REQUIRED":
        checks["job_citations_required"] = bool(citations)
    candidates = [candidate for item in job_preparations for candidate in (item.get("modelData") or {}).get("candidates", [])]
    checks["job_dialogue_no_unevidenced_places"] = not unevidenced_places_named(_texts(result.get("dialogue")), candidates)
    return checks, result, supplied


def _exclusion_checks(
    expected_exclusion: dict[str, Any] | None,
    decision: dict[str, Any],
    exclusions: list[dict[str, Any]],
    job_preparations: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, bool | None]:
    """Requested position → server-resolved ID → applied search filter → absent from what the job returned."""
    if expected_exclusion is None:
        return {"no_unrequested_exclusion": not decision.get("exclude_positions")}
    wanted = expected_exclusion["place_ids"]
    resolved = exclusions[0] if len(exclusions) == 1 else {}
    criteria = (job_preparations[0].get("modelData") or {}).get("searchCriteria") or {} if len(job_preparations) == 1 else {}
    returned = [item.get("placeId") for item in result.get("data") or [] if isinstance(item, dict)]
    return {
        "exclusion_positions": decision.get("exclude_positions") == expected_exclusion["positions"],
        "exclusion_resolved": resolved.get("status") == "RESOLVED" and resolved.get("placeIds") == wanted,
        "exclusion_filter_applied": set(wanted) <= set(criteria.get("excludePlaceIds") or []),
        "exclusion_absent_from_result": bool(returned) and not set(wanted) & set(returned),
    }


def _plan_checks(
    case: dict[str, Any],
    followed: dict[str, Any],
    native: dict[str, Any],
    tool_events: list[dict[str, Any]],
    cut_schema: dict[str, Any] | None,
) -> tuple[dict[str, bool | None], dict[str, Any]]:
    """Accepting the job and finishing the draft are separate results; a failure or timeout is never a draft."""
    job = followed.get("job") or {}
    draft = followed.get("result") if isinstance(followed.get("result"), dict) else None
    accepted = native.get("type") == "PLANNING_JOB" and bool((native.get("data") or {}).get("jobId")) and any(
        (event.get("result") or {}).get("name") == "generate_plan" and (event.get("result") or {}).get("status") == "SUCCEEDED"
        for event in tool_events)
    checks: dict[str, bool | None] = {
        "plan_job_accepted": accepted,
        "plan_job_succeeded": followed.get("kind") == "PLANNING" and not followed.get("timed_out") and job.get("status") == "SUCCEEDED",
        "plan_draft_retrieved": draft is not None and draft.get("planId") == job.get("planId") and bool(draft.get("pins")),
        "plan_draft_dialogue": _valid(cut_schema, draft.get("dialogue") or []) if draft is not None and cut_schema else False,
    }
    content = draft_checks(case["api_request"], {"type": "DRAFT", "data": draft}) if draft is not None else {
        "status": "not_ready", "checks": {}, "route_time_verified": False, "opening_hours_verified": False}
    checks["plan_draft_conditions"] = None if content["status"] == "not_assessed" else content["status"] == "passed"
    return checks, content


def score_lili_case(case: dict[str, Any], record: dict[str, Any], selected: list[dict[str, Any]],
                    contract: dict[str, Any], base_checks: dict[str, bool | None], trace_error: str | None) -> dict[str, Any]:
    expected = case["expected"]
    expected_branch = expected.get("lili_branch")
    native = record.get("native_response") if isinstance(record.get("native_response"), dict) else {}
    followed = record.get("followed_job") or {}
    # Legacy checks assume pre-retrieved places in the chat turn; LiLi's turn is judged by its own rules below.
    checks = {name: value for name, value in base_checks.items() if name not in LEGACY_ONLY_CHECKS}
    routes = _payloads(selected, "ROUTE")
    route = routes[0] if len(routes) == 1 else None
    decision = _decision(route) or {}
    lili = contract.get("lili", {})
    cut_schema = lili.get("recommendation_schema", {}).get("properties", {}).get("dialogue")
    branch = decision.get("branch")
    checks["route_observed"] = route is not None and route.get("stage") == "ROUTER"
    checks["route_schema"] = _valid(lili["router_schema"], decision) if route and "router_schema" in lili else None
    checks["lili_branch"] = branch == expected_branch
    checks["search_query_present"] = bool((decision.get("search_query") or "").strip()) if branch in QUERY_BRANCHES else None
    checks["no_evidence_before_lili"] = not _payloads(selected, "EVIDENCE_PREPARATION", "CONVERSATION")
    tool_events = _payloads(selected, "TOOL_RESULT", "CONVERSATION")
    executed = [item.get("result", {}) for item in tool_events]
    checks["tool_selection"] = [item.get("name") for item in executed] == BRANCH_TOOLS.get(expected_branch, [])
    checks["tools_run_by_server"] = all(item.get("initiator") == "LILI" for item in tool_events)
    arguments = [json.loads(item.get("arguments") or "{}") for item in executed]
    expected_exclusion = expected.get("exclusion")
    if expected_branch == "GET_PLANNING_JOB":
        checks["tool_arguments"] = len(arguments) == 1 and bool(arguments[0].get("job_id")) and arguments[0]["job_id"] in case["api_request"]["message"]
    elif expected_branch == "GENERATE_PLAN":
        checks["tool_arguments"] = arguments == [{}]
    elif expected_branch == "SEARCH_PLACES":
        wanted = expected_exclusion["place_ids"] if expected_exclusion else []
        checks["tool_arguments"] = len(arguments) == 1 and arguments[0].get("query") == decision.get("search_query") \
            and arguments[0].get("exclude_place_ids", []) == wanted
    checks["intent_type"] = native.get("intent") == expected.get("intent")
    checks["message_source"] = native.get("messageSource") == "LLM"
    checks["dialogue_present"] = bool(native.get("dialogue")) and native.get("message") == native["dialogue"][0].get("text")
    expected_type = {"SEARCH_PLACES": "RECOMMENDATION_JOB", "GENERATE_PLAN": "PLANNING_JOB", "GET_PLANNING_JOB": "PLANNING_JOB"}
    checks["response_type"] = native.get("type") == expected_type.get(expected_branch, "TEXT") or (
        expected_branch == "GET_PLANNING_JOB" and native.get("type") in {"PLANNING_JOB", "DRAFT"})
    follow_ups = [item for item in _payloads(selected, "MODEL_TURN") if item.get("stage") == "FOLLOW_UP"]
    # A server-side ask-back (missing job ID or list) is a clarification even when the router picked another branch.
    asked_back = bool(follow_ups) and native.get("type") == "TEXT"
    checks["choices_only_when_clarifying"] = bool(native.get("choices")) <= (branch == "CLARIFY" or asked_back) if branch else None
    citations: list[dict[str, Any]] = []
    supplied: list[dict[str, Any]] = []
    job_result: dict[str, Any] = {}
    job_preparations = _payloads(selected, "EVIDENCE_PREPARATION", "RECOMMENDATION_GENERATION")
    if expected_branch == "SEARCH_PLACES":
        job_checks, job_result, supplied = _recommendation_checks(followed, expected, decision, job_preparations, cut_schema)
        checks.update(job_checks)
        checks.update(_exclusion_checks(expected_exclusion, decision, _payloads(selected, "EXCLUSION"), job_preparations, job_result))
        citations = job_result.get("citations") or []
    plan_content = {"status": "not_applicable", "checks": {}, "route_time_verified": False, "opening_hours_verified": False}
    draft = followed.get("result") if isinstance(followed.get("result"), dict) else {}
    if expected.get("plan_outcome") == DRAFT_COMPLETED:
        plan_check_values, plan_content = _plan_checks(case, followed, native, tool_events, cut_schema)
        checks.update(plan_check_values)
    # The draft's title, description and pin explanations are shown to the user as they are, like LiLi's lines.
    shown_plan = [draft.get("title") or "", draft.get("description") or ""] + [
        pin.get("explanation") or "" for pin in draft.get("pins") or []]
    spoken = _texts(native.get("dialogue")) + _texts(job_result.get("dialogue")) + _texts(draft.get("dialogue")) + shown_plan
    leaked = internal_terms(spoken)
    checks["no_internal_terms"] = not leaked
    model_calls = [item for item in _payloads(selected, "MODEL_CALL") if item.get("stage") == "FINISHED"]
    checks["provider_identity"] = all(call.get("provider") == contract["provider"] and call.get("model") == contract["model"]
                                      for call in model_calls) if model_calls else None
    automated = "failed" if any(value is False for value in checks.values()) else "not_assessed" if any(
        value is None for name, value in checks.items() if name in {"route_observed", "trace_binding", "lili_branch"}) else "passed"
    live = record.get("execution_mode") == "LIVE"
    job_turns = [item for item in _payloads(selected, "MODEL_TURN") if item.get("stage") == "RECOMMENDATION"]
    plan_drafts = _payloads(selected, "PLAN_DRAFT", "PLAN_GENERATION")
    criteria = list(expected["semantic_criteria"])
    if branch in QUERY_BRANCHES:
        criteria.append(ROUTER_LINE_CRITERION)
    usage = [call.get("receipt", {}).get("usage") for call in model_calls]
    return {"case_id": case["case_id"], "input_sha256": case["input_sha256"], "automated_status": automated,
            "checks": checks, "not_applicable_checks": [name for name, value in checks.items() if value is None],
            "trace_error": trace_error, "lili_decision": decision, "internal_terms_found": leaked,
            "stage_results": {"plan_accepted": checks.get("plan_job_accepted"),
                              "plan_draft_completed": checks.get("plan_draft_retrieved")} if "plan_job_accepted" in checks else None,
            "plan_generation": [{"status": item.get("status"), "failureType": item.get("failureType"),
                                 "failureMessage": item.get("failureMessage"), "outputPresent": bool(item.get("output")),
                                 "candidateIds": item.get("candidateIds")} for item in plan_drafts],
            "response_text": " / ".join(_texts(native.get("dialogue"))) or native.get("message"),
            "job_response_text": " / ".join(_texts(job_result.get("dialogue"))) or None,
            "draft_dialogue_text": " / ".join(_texts(draft.get("dialogue"))) or None,
            "plan_draft": _draft_summary(draft),
            "job_status": {"kind": followed.get("kind"), "status": (followed.get("job") or {}).get("status"),
                           "errorMessage": (followed.get("job") or {}).get("errorMessage"),
                           "timedOut": followed.get("timed_out")} if followed else None,
            "tool_results": [{"name": item.get("name"), "status": item.get("status"), "type": item.get("type")}
                             for item in native.get("toolResults") or []],
            "review_candidates": _review_candidates(job_preparations, plan_drafts),
            "citations": citations, "model_tool_calls": [], "supplied_evidence": supplied,
            "question": case["api_request"]["message"], "semantic_criteria": criteria,
            "acceptable_response_example": expected["message_example"], "semantic_status": "not_reviewed",
            "quality_observed": live and bool(model_calls) and all(call.get("status") == "SUCCEEDED" for call in model_calls),
            "plan_content": plan_content,
            "observed_calls": {"model_calls": len(model_calls), "router_calls": len(routes), "follow_up_calls": len(follow_ups),
                               "recommendation_calls": len(job_turns), "server_tool_executions": len(tool_events),
                               "job_retrievals": len(job_preparations), "job_polls": followed.get("polls")},
            "latency_ms": {"conversation_http": record.get("duration_ms") if live else None,
                           "router": route.get("durationMs") if live and route else None,
                           "follow_up": [item.get("durationMs") for item in follow_ups] if live else None,
                           "tool_execution": [item.get("durationMs") for item in tool_events] if live else None,
                           "job_wait": followed.get("wait_ms") if live else None,
                           "job_pre_retrieval": job_preparations[0].get("durationMs") if live and len(job_preparations) == 1 else None,
                           "job_inference": [item.get("durationMs") for item in job_turns] if live else None},
            "observed_usage": usage if live else None,
            "quality_status": "mock_regression_only" if record.get("execution_mode") == "MOCK" else "semantic_review_required",
            "record_sha256": canonical_digest(record), "events_sha256": canonical_digest(selected)}
