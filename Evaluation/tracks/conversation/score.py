"""Separate execution correctness, exact source checks and human semantic judgment."""
from __future__ import annotations

import json
import argparse
import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
import sys
from typing import Any, Callable
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tracks.conversation.lili_score import score_lili_case
from tracks.conversation.plan_checks import draft_checks
from common.dataset.io import canonical_digest, digest, read_json, read_jsonl
from common.experiments.contracts import ConversationRouting, select_for_routing
from common.paths import EVALUATION_ROOT

# Same resource the Spring pre-retrieval reads; the check fails if the server uses a different template.
THEME_HINT_TEMPLATE = EVALUATION_ROOT.parent / "Server/TravelMate/src/main/resources/conversation/queries/v1-theme-hint.txt"
THEME_SEPARATOR = ", "
TEMPLATE_TOKEN = re.compile(r"\{\{([A-Za-z]+)}}")


@cache
def theme_hint_template() -> str:
    return THEME_HINT_TEMPLATE.read_text(encoding="utf-8").rstrip()


def expected_pre_retrieval_query(message: str, themes: list[str]) -> str:
    if not themes:
        return message
    values = {"message": message, "themes": THEME_SEPARATOR.join(themes)}
    # One pass, like the server renderer, so braces inside the user's message are never re-expanded.
    return TEMPLATE_TOKEN.sub(lambda match: values[match.group(1)], theme_hint_template())


def bound_events(case: dict[str, Any], record: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    native = record.get("native_response") or {}
    if not isinstance(native, dict):
        raise ValueError("Actual server response is not an object")
    request_id = native.get("requestId")
    if not request_id:
        raise ValueError("Missing actual server request identity")
    selected = [event for event in events if event.get("requestId") == request_id]
    if not selected or any(event.get("caseId") != case["case_id"] or event.get("inputSha256") != case["input_sha256"]
                           or event.get("mode") != record["execution_mode"] for event in selected):
        raise ValueError("Observation identity, input hash or LIVE/MOCK binding mismatch")
    if len({event["eventId"] for event in selected}) != len(selected):
        raise ValueError("Duplicate observation IDs")
    requests = [event["payload"] for event in selected if event["event"] == "API_REQUEST"]
    responses = [event["payload"] for event in selected if event["event"] == "API_RESPONSE"]
    finals = [event["payload"] for event in selected if event["event"] == "TURN_RESULT"]
    if len(requests) != 1 or len(responses) != 1 or finals != [native]:
        raise ValueError("Actual API input, response and final result must each be observed once")
    request = record["http_request"]
    if hashlib.sha256(request["raw_body"].encode("utf-8")).hexdigest() != request["body_sha256"]:
        raise ValueError("Original request body hash is invalid")
    if native.get("turnId") != request["headers"].get("Idempotency-Key") or native.get("conversationId") != request["headers"].get("X-Conversation-Id"):
        raise ValueError("Server turn/conversation identity differs from the submitted request")
    if requests[0].get("bodySha256") != request["body_sha256"] or requests[0].get("rawBody") != request["raw_body"]:
        raise ValueError("Captured request differs from the actual submitted UTF-8 body")
    if responses[0].get("httpStatus") != 200 or responses[0].get("response") != native:
        raise ValueError("HTTP 200 or final response identity mismatch")
    return selected


def score_case(case: dict[str, Any], record: dict[str, Any], events: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected"]
    supplied_native = record.get("native_response")
    native = supplied_native if isinstance(supplied_native, dict) else {}
    checks: dict[str, bool | None] = {**(record.get("contract_checks") or {})}
    checks["response_object"] = isinstance(supplied_native, dict)
    checks["message_present"] = isinstance(native.get("message"), str) and bool(native.get("message", "").strip())
    checks["response_type"] = native.get("type") in expected["response_types"]
    checks["message_source"] = native.get("messageSource") in expected["message_sources"]
    checks["emotion_tag"] = native.get("emotion") in contract["answer_schema"]["properties"]["emotion"]["enum"]
    expected_intent = {"PLACES": "RECOMMENDATION", "DRAFT": "PLAN", "PLANNING_JOB": "PLAN", "TEXT": "CONVERSATION", "ERROR": "CONVERSATION"}
    checks["intent_type"] = native.get("intent") == expected.get("intent", expected_intent.get(native.get("type")))
    expected_items = native.get("data") if native.get("type") == "PLACES" else [native.get("data")] if native.get("type") == "DRAFT" else []
    checks["array_result_preserved"] = isinstance(native.get("items"), list) and native.get("items") == expected_items
    # Same rule as the run-time completion contract: a plan the server refuses ends TOOL_FAILED by design.
    endings = {"COMPLETED", "TOOL_FAILED"} if expected.get("plan_outcome") == "REJECTED" else {"COMPLETED"}
    checks["completed"] = native.get("termination") in endings
    trace_error = None
    selected: list[dict[str, Any]] = []
    try:
        selected = bound_events(case, record, events)
        checks["trace_binding"] = True
    except (ValueError, KeyError, TypeError) as exception:
        trace_error = str(exception)
        checks["trace_binding"] = None if not events else False
    # LiLi decides before any evidence and the server runs her tool, so each routing has its own trace rules.
    scorer = select_for_routing(CASE_SCORERS, ConversationRouting.of(contract))
    return scorer.score(case, record, selected, contract, checks, trace_error)


def score_single_llm_case(
    case: dict[str, Any],
    record: dict[str, Any],
    selected: list[dict[str, Any]],
    contract: dict[str, Any],
    checks: dict[str, bool | None],
    trace_error: str | None,
) -> dict[str, Any]:
    expected = case["expected"]
    native = record.get("native_response") if isinstance(record.get("native_response"), dict) else {}
    preparations = [event["payload"] for event in selected if event["event"] == "EVIDENCE_PREPARATION"]
    turns = [event["payload"] for event in selected if event["event"] == "MODEL_TURN"]
    tool_events = [event["payload"] for event in selected if event["event"] == "TOOL_RESULT"]
    calls = [call for turn in turns for call in turn.get("toolCalls", [])]
    schemas = {tool["name"]: tool["parameters"] for tool in contract["tools"]}
    checks["model_tool_selection"] = [call["name"] for call in calls] == expected["tool_names"] if selected else None
    checks["one_model_turn_observed"] = len(turns) == 1 if selected else None
    checks["pre_retrieval_observed"] = len(preparations) == 1 and preparations[0].get("state") in {"READY", "EMPTY"} if selected else None
    checks["prepared_metadata_preserved"] = None
    checks["prepared_query_preserved"] = None
    if len(preparations) == 1:
        criteria = preparations[0].get("modelData", {}).get("searchCriteria", {})
        supplied_context = case["api_request"].get("searchContext") or {}
        actual_area = criteria.get("area")
        expected_area = supplied_context.get("area")
        area_matches = actual_area is None if expected_area is None else isinstance(actual_area, dict) and all(actual_area.get(key) == expected_area.get(key) for key in ("type", "center", "radiusMeters"))
        checks["prepared_metadata_preserved"] = bool(criteria) and area_matches and all(
            criteria.get(key) == supplied_context.get(key) for key in ("region", "city", "category")
        ) and criteria.get("excludePlaceIds") == supplied_context.get("excludePlaceIds", [])
        expected_query = expected_pre_retrieval_query(case["api_request"]["message"], supplied_context.get("themes") or [])
        checks["prepared_query_preserved"] = criteria.get("query") == expected_query
    observed_results = [item["result"] for item in tool_events]
    checks["executed_tools_match_trace"] = observed_results == native.get("toolResults") if selected else None
    checks["tool_execution_identity"] = all(
        any(result.get("callId") == call["id"] and result.get("name") == call["name"]
            and result.get("arguments") == call["arguments"] and result.get("status") in {"SUCCEEDED", "CACHED"}
            for result in observed_results) for call in calls
    ) if selected else None
    argument_checks = []
    for index, call in enumerate(calls):
        try:
            arguments = json.loads(call["arguments"])
            valid = call["name"] in schemas and not list(Draft202012Validator(schemas[call["name"]]).iter_errors(arguments))
            requirement = expected["arguments"][index]
            if "equals" in requirement:
                valid = valid and arguments == requirement["equals"]
            if requirement.get("exclude_first_prepared_place"):
                first = preparations[0]["publicData"][0]["placeId"]
                valid = valid and first in (arguments.get("exclude_place_ids") or [])
                results = [item for item in tool_events if item["result"]["callId"] == call["id"]]
                effective = results[0]["modelData"]["searchCriteria"]
                valid = valid and first in effective["excludePlaceIds"]
                valid = valid and all(effective.get(key) == value for key, value in requirement["effective_filters"].items())
                valid = valid and all(place["placeId"] != first for place in results[0]["result"]["publicData"])
            argument_checks.append(bool(valid))
        except (ValueError, KeyError, TypeError, IndexError):
            argument_checks.append(False)
    checks["tool_arguments"] = all(argument_checks) and len(calls) == len(expected["arguments"]) if selected else None

    checks["answer_json_schema"] = None
    checks["answer_kind"] = None
    not_applicable = []
    if selected and not calls and len(turns) == 1:
        try:
            answer = json.loads(turns[0]["content"])
            checks["answer_json_schema"] = not list(Draft202012Validator(contract["answer_schema"]).iter_errors(answer))
            checks["answer_kind"] = answer.get("answerKind") in expected["answer_kinds"]
            checks["message_preserved"] = answer.get("message") == native.get("message")
            checks["intent_preserved"] = answer.get("intent") == native.get("intent")
            checks["emotion_preserved"] = answer.get("emotion") == native.get("emotion")
        except (ValueError, KeyError, TypeError):
            checks["answer_json_schema"] = False
            checks["answer_kind"] = False
    elif selected and calls:
        # Tool call content may be empty/afterTool, not a fabricated final answer.
        not_applicable = ["answer_json_schema", "answer_kind"]

    sources: dict[str, dict[str, Any]] = {}
    supplied_evidence = []
    for model_data in [item.get("modelData", {}) for item in preparations + tool_events]:
        for candidate in model_data.get("candidates", []):
            for evidence in candidate.get("selectedEvidence", []):
                original = evidence.get("original", {})
                entry = {"placeId": candidate["placeId"], "sourceId": original.get("source_id"), "text": original.get("chunk_text")}
                identifier = evidence["evidenceId"]
                if identifier in sources and sources[identifier] != entry:
                    checks["source_identity_unique"] = False
                sources[identifier] = entry
                supplied_evidence.append({"evidenceId": identifier, **entry})
    citations = native.get("citations")
    policy = expected["citations"]
    checks["citation_count"] = isinstance(citations, list) and (bool(citations) if policy == "REQUIRED" else not citations if policy == "FORBIDDEN" else True)
    checks["citation_original_membership"] = None
    if selected:
        checks["citation_original_membership"] = isinstance(citations, list) and all(
            isinstance(citation, dict) and isinstance(citation.get("quote"), str) and bool(citation["quote"].strip())
            and (source := sources.get(citation.get("evidenceId"))) is not None
            and source["placeId"] == citation.get("placeId") and source["sourceId"] == citation.get("sourceId")
            and isinstance(source["text"], str) and citation["quote"] in source["text"] for citation in citations or []
        )
        public_results = [(item.get("result", {}).get("type"), item.get("result", {}).get("publicData")) for item in tool_events]
        public_results += [("PLACES", item.get("publicData")) for item in preparations if item.get("state") in {"READY", "EMPTY"}]
        checks["server_data_preserved"] = native.get("data") is None if native.get("type") == "TEXT" else (native.get("type"), native.get("data")) in public_results
    else:
        checks["server_data_preserved"] = None
    provider_calls = [event["payload"] for event in selected if event["event"] == "MODEL_CALL"
                      and event.get("phase") == "CONVERSATION" and event["payload"].get("stage") == "FINISHED"]
    live_observed = record.get("execution_mode") == "LIVE" and len(provider_calls) == 1 and provider_calls[0].get("dispatched") is True and provider_calls[0].get("status") == "SUCCEEDED"
    checks["provider_identity"] = (len(provider_calls) == 1 and provider_calls[0].get("provider") == contract["provider"]
                                   and provider_calls[0].get("model") == contract["model"]) if provider_calls else None
    applicable = [value for name, value in checks.items() if name not in not_applicable]
    automated = "failed" if any(value is False for value in applicable) else "not_assessed" if any(value is None for value in applicable) else "passed"
    plan = draft_checks(case["api_request"], native)
    if plan["status"] == "failed":
        automated = "failed"
    live = record.get("execution_mode") == "LIVE"
    timing = provider_calls[0] if len(provider_calls) == 1 else {}
    return {"case_id": case["case_id"], "input_sha256": case["input_sha256"], "automated_status": automated,
            "checks": checks, "not_applicable_checks": not_applicable, "trace_error": trace_error, "response_text": native.get("message"), "citations": citations,
            "model_tool_calls": calls, "supplied_evidence": supplied_evidence, "question": case["api_request"]["message"],
            "semantic_criteria": expected["semantic_criteria"], "acceptable_response_example": expected["message_example"],
            "semantic_status": "not_reviewed", "quality_observed": live_observed,
            "plan_content": plan,
            "observed_calls": {"conversation_model_turns": len(turns) if selected else None,
                               "conversation_inference_dispatches": sum(call.get("dispatched") is True for call in provider_calls) if selected else None,
                               "server_pre_retrievals": len(preparations) if selected else None,
                               "model_selected_tool_executions": len(tool_events) if selected else None},
            "latency_ms": {"conversation_http": record.get("duration_ms") if live else None,
                           "pre_retrieval": preparations[0].get("durationMs") if live and len(preparations) == 1 else None,
                           "inference_http": timing.get("inferenceDurationMs") if live else None,
                           "token_count_http": timing.get("countDurationMs") if live else None,
                           # One entry per model-selected tool; separates search/job latency from model latency.
                           "tool_execution": [item.get("durationMs") for item in tool_events] if live else None},
            "observed_usage": timing.get("receipt", {}).get("usage") if live else None,
            "quality_status": "mock_regression_only" if record.get("execution_mode") == "MOCK" else "semantic_review_required",
            "record_sha256": canonical_digest(record), "events_sha256": canonical_digest(selected)}


@dataclass(frozen=True)
class RoutingCaseScorer:
    routing: ConversationRouting
    score: Callable[..., dict[str, Any]]

    def supports(self, routing: ConversationRouting) -> bool:
        return routing == self.routing


CASE_SCORERS = (
    RoutingCaseScorer(ConversationRouting.SINGLE_LLM_V1, score_single_llm_case),
    RoutingCaseScorer(ConversationRouting.LILI_ROUTER_V1, score_lili_case),
)


def main() -> None:
    from tracks.conversation.cases import DEFAULT_SUITE, load_cases
    from tracks.conversation.review import summarize
    from tracks.conversation.log_types import TestLogPath
    from tracks.conversation.test_logs import TestLogs
    from common.paths import EVALUATION_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    manifest = read_json(TestLogs.path(arguments.run_dir, TestLogPath.RUN))
    if digest(arguments.suite) != manifest["suite_sha256"]:
        raise ValueError("The expectation suite differs from the collected run")
    bindings = read_json(arguments.bindings) if arguments.bindings is not None else {}
    cases = load_cases(arguments.suite, tuple(manifest["selected_case_ids"]), bindings)
    indexed = {case["case_id"]: case for case in cases}
    records = read_jsonl(TestLogs.path(arguments.run_dir, TestLogPath.RECORDS))
    if len({record["case_id"] for record in records}) != len(records):
        raise ValueError("Duplicate case observations")
    contract = read_json(TestLogs.path(arguments.run_dir, TestLogPath.SERVER_CONTRACT))
    events = read_jsonl(TestLogs.path(arguments.run_dir, TestLogPath.EVENTS))
    scores = []
    for record in records:
        case = indexed[record["case_id"]]
        if case["input_sha256"] != record["input_sha256"]:
            raise ValueError("Runtime binding or original case input hash changed")
        scores.append(score_case(case, record, events, contract))
    summary = summarize(scores, expected_count=len(cases), review_path=arguments.review)
    output = arguments.output_dir.resolve()
    if output.is_relative_to(EVALUATION_ROOT / "datasets"):
        raise ValueError("Scores cannot modify versioned datasets")
    output.mkdir(parents=True, exist_ok=False)
    TestLogs.write(output, TestLogPath.REVIEW, scores)
    TestLogs.write(output, TestLogPath.SCORES, scores)
    TestLogs.write(output, TestLogPath.SUMMARY, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
