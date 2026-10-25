"""Compose the existing per-track checks without changing metric policy."""
from __future__ import annotations

from typing import Any
import json
from jsonschema import Draft202012Validator
from common.dataset.contracts import ENVELOPE_SCHEMA
from common.metrics.ranking import ranking_metrics
from tracks.tool_call.score_args import normalize_call, tool_metrics
from tracks.plan.score_rules import plan_metrics
from tracks.state.score import state_metrics
from tracks.memory.score_retrieval import score_retrieval
from tracks.memory.score_extraction import score_extraction


def provenance_metrics(record: dict[str, Any], response: dict[str, Any]) -> dict[str, float | None]:
    primary_id = record.get("primary_result_id")
    if primary_id is None:
        return {"server_data_unchanged": None, "server_type_matches_primary_result": None}
    results = {result["result_id"]: result for result in (record.get("tool_results") or []) if isinstance(result, dict) and "result_id" in result}
    result = results.get(primary_id)
    if not result or result.get("status") != "completed":
        return {"server_data_unchanged": 0.0, "server_type_matches_primary_result": 0.0}
    return {
        "server_data_unchanged": float(response.get("data") == result.get("public_data")),
        "server_type_matches_primary_result": float(response.get("type") == result.get("response_type")),
    }


def evaluate_record(case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    response = record.get("response", {})
    schema_errors = list(Draft202012Validator(ENVELOPE_SCHEMA).iter_errors(response))
    metrics: dict[str, float | None] = {
        "response_type_accuracy": float(isinstance(response, dict) and response.get("type") == case["expected_response_type"]),
        "envelope_schema_valid": float(not schema_errors),
        "conversation_id_matches": float(isinstance(response, dict) and response.get("conversationId") == case["input"]["conversationId"]),
    }
    issues = [f"{list(error.path)}: {error.message}" for error in schema_errors]
    try:
        calls = [normalize_call(call) for call in record.get("tool_calls", [])]
        metrics.update(tool_metrics(case, calls))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        calls = []
        metrics.update(tool_argument_schema_valid=0.0, tool_name_and_hard_args_accuracy=0.0, tool_precision=0.0, tool_recall=0.0, tool_f1=0.0)
        issues.append("Malformed tool-call record")
    if isinstance(response, dict):
        metrics.update(provenance_metrics(record, response))
        try:
            metrics.update(plan_metrics(case, calls, response))
        except (ValueError, KeyError, TypeError):
            issues.append("Invalid plan data or route fixture")
            metrics.update(route_time_consistent=0.0, schedule_within_window=0.0)
        metrics.update(state_metrics(case, record, response))
    search = case["expectations"]["search"]
    if search and isinstance(response, dict):
        data = response.get("data")
        returned = [place["placeId"] for place in data if isinstance(place, dict) and type(place.get("placeId")) is int] if isinstance(data, list) else []
        judgments = {item["place_id"]: item["relevance"] for item in case["place_judgments"]}
        metrics.update(ranking_metrics(returned, judgments))
        metrics["returned_place_ids_unique"] = float(len(set(returned)) == len(returned))
        metrics["judged_at_5"] = sum(place_id in judgments for place_id in returned[:5])
        metrics["judged_at_10"] = sum(place_id in judgments for place_id in returned[:10])
    metrics.update(score_retrieval(case, record))
    metrics.update(score_extraction(case, record))
    return {"metrics": metrics, "issues": issues}
