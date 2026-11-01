"""Convert captured Spring execution events without calling application or model APIs."""
from __future__ import annotations

import argparse
import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from common.dataset.io import canonical_digest, read_jsonl, write_jsonl
from common.dataset.contracts import TOOL_ARGUMENT_SCHEMAS
from jsonschema import Draft202012Validator


class RecordMode(StrEnum):
    MOCK = "MOCK"
    LIVE = "LIVE"


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("payload") or {}


def _unique(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for event in events:
        identifier = event.get("eventId")
        if not identifier:
            raise ValueError("Every captured event needs its actual eventId")
        if identifier in indexed and indexed[identifier] != event:
            raise ValueError("Conflicting event IDs")
        indexed[identifier] = event
    return list(indexed.values())


def _arguments_compatible(calls: list[dict[str, Any]]) -> bool:
    try:
        return all(call["function"]["name"] in TOOL_ARGUMENT_SCHEMAS
                   and not list(Draft202012Validator(TOOL_ARGUMENT_SCHEMAS[call["function"]["name"]])
                                .iter_errors(json.loads(call["function"]["arguments"]))) for call in calls)
    except (ValueError, TypeError, KeyError):
        return False


def _conditions_covered(expected: dict[str, Any], request: dict[str, Any]) -> bool:
    if any(value not in (None, [], "", {}) for name, value in expected.items() if name != "area"):
        return False
    native = (request.get("planningRequest") or {}).get("context", {}).get("area")
    area = expected.get("area")
    if not area:
        return native is None
    if not native or str(area.get("type")).lower() != "circle":
        return False
    return (native.get("type") == "CIRCLE"
            and native.get("center") == {"lat": area["center"]["latitude"], "lon": area["center"]["longitude"]}
            and native.get("radiusMeters") == area["radius_meters"])


def _usage_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    dispatched = [_payload(event) for event in events if _payload(event).get("dispatched") is True]
    summary: dict[str, Any] = {"observed_attempts": len(events), "observed_dispatched_calls": len(dispatched)}
    for field in ("inputTokens", "outputTokens", "reasoningTokens", "cachedInputTokens"):
        values = [row.get("receipt", {}).get("usage", {}).get(field) for row in dispatched]
        known = [value for value in values if type(value) is int]
        summary[field] = {"known_sum": sum(known) if known else None, "observed_count": len(known),
                          "missing_count": len(values) - len(known)}
    return summary


def convert_records(
    events: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    exported_inputs: list[dict[str, Any]],
    *,
    mode: RecordMode,
) -> list[dict[str, Any]]:
    captured = _unique(events)
    inputs = {row["case_id"]: row for row in exported_inputs}
    if len(inputs) != len(exported_inputs):
        raise ValueError("Duplicate exported case IDs")
    if len({row["case_id"] for row in bindings}) != len(bindings):
        raise ValueError("One explicitly bound request is required per case")
    if len({row["request_id"] for row in bindings}) != len(bindings):
        raise ValueError("A captured request cannot stand for multiple cases")
    return [_convert(captured, binding, inputs, mode) for binding in bindings]


def _convert(
    events: list[dict[str, Any]],
    binding: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    mode: RecordMode,
) -> dict[str, Any]:
    case_id = binding["case_id"]
    if case_id not in inputs:
        raise ValueError("The binding does not refer to an exported existing case")
    exported = inputs[case_id]
    expected_hash = canonical_digest({
        "model_input": exported["model_input"],
        "harness_fixtures": exported["harness_fixtures"],
    })
    if exported["input_sha256"] != expected_hash or binding["input_sha256"] != expected_hash:
        raise ValueError("Exported input or binding hash mismatch")
    request_id = binding["request_id"]
    selected = [event for event in events if event.get("requestId") == request_id]
    if not selected or any(event.get("mode") != mode.value for event in selected):
        raise ValueError("Missing captured request or mixed mock/live evidence")
    if any(event.get("caseId") != case_id or event.get("inputSha256") != expected_hash for event in selected):
        raise ValueError("Captured request does not carry the explicit evaluation binding")
    requests = [event for event in selected if event["event"] == "API_REQUEST"]
    responses = [event for event in selected if event["event"] == "API_RESPONSE"]
    finals = [event for event in selected if event["event"] == "TURN_RESULT"]
    if len(requests) != 1 or len(responses) != 1 or len(finals) != 1:
        raise ValueError("Actual API input, response and turn termination must each be observed once")
    request = _payload(requests[0])
    raw_body = request["rawBody"]
    if hashlib.sha256(raw_body.encode("utf-8")).hexdigest() != request["bodySha256"]:
        raise ValueError("Captured API body hash mismatch")
    actual_request = json.loads(raw_body)
    if canonical_digest(actual_request) != canonical_digest(binding["api_request"]):
        raise ValueError("Observed API payload differs from the explicit request binding")
    if actual_request.get("message") != exported["model_input"]["query"]:
        raise ValueError("The API question differs from the existing exported question")
    response_event = _payload(responses[0])
    native = _payload(finals[0])
    if response_event.get("httpStatus") != 200 or response_event.get("response") != native:
        raise ValueError("Turn result differs from the actual successful API response")
    if native.get("requestId") != request_id or not native.get("turnId") or not native.get("conversationId"):
        raise ValueError("Server request/turn/conversation identity is missing")
    if native["conversationId"] != exported["model_input"]["conversationId"]:
        raise ValueError("The observed conversation ID differs from the input; it cannot be fabricated afterwards")
    turns = [event for event in selected if event["event"] == "MODEL_TURN"]
    calls = [
        {"id": call["id"], "type": "function", "function": {
            "name": call["name"], "arguments": call["arguments"],
        }}
        for turn in turns for call in _payload(turn)["toolCalls"]
    ]
    tool_events = [_payload(event) for event in selected if event["event"] == "TOOL_RESULT"]
    observed_tools = [event["result"] for event in tool_events]
    if observed_tools != native.get("toolResults"):
        raise ValueError("Final tool artifacts differ from the actual execution observations")
    results = [{
        "result_id": result["resultId"],
        "status": "failed" if result["status"] == "FAILED" else "completed",
        "response_type": result["type"],
        "public_data": result["publicData"],
        "llm_summary": tool_event.get("modelData"),
        "cache_hit": result["status"] == "CACHED",
        "call_id": result["callId"],
    } for result, tool_event in zip(observed_tools, tool_events, strict=True)]
    primary = native.get("primaryResultId")
    if primary is not None:
        artifact = next((result for result in results if result["result_id"] == primary), None)
        if artifact is None or artifact["public_data"] != native.get("data") or artifact["response_type"] != native.get("type"):
            raise ValueError("Server primary artifact provenance mismatch")
    job_ids = {event["jobId"] for event in selected if event.get("jobId")}
    job_ids.update(result["publicData"]["jobId"] for result in observed_tools
                   if isinstance(result.get("publicData"), dict) and result["publicData"].get("jobId"))
    linked = [event for event in events if event.get("jobId") in job_ids]
    if any(event.get("mode") != mode.value for event in linked):
        raise ValueError("Job history mixes mock/live sources")
    finished_calls = [event for event in selected if event["event"] == "MODEL_CALL"
                      and _payload(event).get("stage") == "FINISHED"]
    linked_calls = [event for event in linked if event["event"] == "MODEL_CALL"
                    and _payload(event).get("stage") == "FINISHED" and event["requestId"] != request_id]
    compatibility: list[str] = []
    if native["type"] not in {"TEXT", "PLACES", "CLARIFICATION", "PLAN", "PLAN_DIFF"}:
        compatibility.append("native_response_type_has_no_legacy_envelope_equivalent")
    if any(call["function"]["name"] in {"generate_plan", "get_planning_job"} for call in calls):
        compatibility.append("async_draft_tools_are_not_legacy_preview_create_plan")
    if exported["model_input"].get("conditions"):
        compatibility.append("structured_condition_and_corpus_coverage_require_separate_verification")
    completed_chats = [event for event in finished_calls if event.get("phase") == "CONVERSATION"
                       and _payload(event).get("status") == "SUCCEEDED"]
    if len(completed_chats) != len(turns):
        compatibility.append("provider_call_observations_incomplete")
    tools_compatible = _arguments_compatible(calls)
    if not tools_compatible:
        compatibility.append("native_tool_argument_schema_differs_from_frozen_contract")
    complete = (mode == RecordMode.LIVE and native["termination"] == "COMPLETED"
                and len(turns) > 0 and len(completed_chats) == len(turns))
    legacy_type = native["type"] in {"TEXT", "PLACES", "CLARIFICATION", "PLAN", "PLAN_DIFF"}
    runtime = binding.get("runtime_verification") or {}
    search_verified = (runtime.get("corpus_verified") is True and runtime.get("configuration_verified") is True
                       and isinstance(runtime.get("corpus_sha256"), str) and len(runtime["corpus_sha256"]) == 64)
    coverage = {
        "response_type": complete and legacy_type,
        "tool_call": complete and tools_compatible,
        "message": complete and legacy_type and native.get("messageSource") == "LLM",
        "search": complete and native["type"] == "PLACES" and search_verified
                  and _conditions_covered(exported["model_input"].get("conditions") or {}, actual_request),
        "plan": False, "state": False, "memory": False,
    }
    envelope = {name: native[name] for name in ("type", "message", "data", "conversationId")}
    providers = sorted({f'{_payload(event).get("provider")}:{_payload(event).get("model")}'
                        for event in finished_calls + linked_calls})
    return {
        "case_id": case_id, "input_sha256": expected_hash,
        "record_source": "spring_execution_mock" if mode == RecordMode.MOCK else "spring_execution_live",
        "execution_mode": mode.value, "request_id": request_id, "turn_id": native["turnId"],
        "api_input_sha256": request["bodySha256"], "api_request": actual_request,
        "model": ",".join(providers) if providers else "not_observed",
        "response": envelope, "native_response": native,
        "tool_calls": calls, "tool_results": results, "primary_result_id": primary,
        "termination": native["termination"], "model_calls": finished_calls,
        "usage_summary": _usage_summary(finished_calls),
        "observation_coverage": coverage,
        "linked_job_model_calls": linked_calls, "job_ids": sorted(job_ids),
        "job_timeline": [event for event in linked if event["event"] == "JOB_STATUS"],
        "compatibility_gaps": compatibility,
        "missing_observations": ["plan_before", "plan_after", "trusted_route_costs"],
        "quality_status": "mock_regression_only" if mode == RecordMode.MOCK else "recorded_not_scored",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--exported-inputs", type=Path, required=True)
    parser.add_argument("--mode", type=RecordMode, choices=list(RecordMode), required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError("Conversion must not overwrite an existing record file")
    records = convert_records(read_jsonl(arguments.events), read_jsonl(arguments.bindings),
                              read_jsonl(arguments.exported_inputs), mode=arguments.mode)
    write_jsonl(arguments.output, records)


if __name__ == "__main__":
    main()
