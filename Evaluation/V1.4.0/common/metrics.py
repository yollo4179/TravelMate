"""Code checks for server envelopes, tool arguments and observed effects."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import math
from typing import Any

from jsonschema import Draft202012Validator

from .contracts import ENVELOPE_SCHEMA, TOOL_ARGUMENT_SCHEMAS, ResponseType, ToolName
from .routing import optimal_route, route_cost


def ranking_metrics(returned: list[Any], judgments: dict[Any, int], prefix: str = "") -> dict[str, float]:
    relevant = {identifier for identifier, grade in judgments.items() if grade >= 2}
    scores = {prefix + "top_1_accuracy": float(bool(returned) and returned[0] in relevant)}
    for cutoff in (5, 10):
        top = returned[:cutoff]
        hits = set(top).intersection(relevant)
        precision = len(hits) / cutoff
        recall = len(hits) / len(relevant) if relevant else 0.0
        ranks = [rank for rank, identifier in enumerate(top, 1) if identifier in relevant and identifier not in top[:rank - 1]]
        dcg = sum((2 ** judgments.get(identifier, 0) - 1) / math.log2(rank + 1) for rank, identifier in enumerate(top, 1) if identifier not in top[:rank - 1])
        ideal = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(sorted(judgments.values(), reverse=True)[:cutoff], 1))
        scores.update({
            prefix + f"top_{cutoff}_accuracy": float(bool(hits)),
            prefix + f"recall_at_{cutoff}": recall,
            prefix + f"precision_at_{cutoff}": precision,
            prefix + f"f1_at_{cutoff}": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            prefix + f"mrr_at_{cutoff}": 1 / ranks[0] if ranks else 0.0,
            prefix + f"map_at_{cutoff}": sum(len(set(top[:rank]).intersection(relevant)) / rank for rank in ranks) / min(len(relevant), cutoff) if relevant else 0.0,
            prefix + f"ndcg_at_{cutoff}": dcg / ideal if ideal else 0.0,
        })
    return scores


def normalize_call(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("tool call must be an object")
    function = raw.get("function", raw)
    if not isinstance(function, dict):
        raise ValueError("tool function must be an object")
    arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be JSON objects")
    return {"name": function.get("name"), "arguments": arguments}


def call_matches(actual: dict[str, Any], expected: dict[str, Any], case: dict[str, Any]) -> bool:
    if actual["name"] != expected["name"]:
        return False
    flexible = case["expectations"]["tool_call"].get("select_place_ids_flexibly")
    plan = case["expectations"]["plan"]
    for key, expected_value in expected["arguments"].items():
        value = actual["arguments"].get(key, [] if expected_value == [] else None)
        if key == "query":
            continue  # Meaning is scored by the MD judge; this metric covers hard arguments only.
        if key == "place_ids" and flexible and plan:
            if not isinstance(value, list) or len(value) != len(set(value)):
                return False
            if not set(value) <= set(plan["allowed_place_ids"]) or not set(plan["required_place_ids"]) <= set(value):
                return False
        elif isinstance(expected_value, list):
            if not isinstance(value, list) or sorted(value) != sorted(expected_value):
                return False
        elif value != expected_value:
            return False
    return True


def matched_call_count(actual: list[dict[str, Any]], expected: list[dict[str, Any]], case: dict[str, Any]) -> int:
    matched: dict[int, int] = {}

    def augment(expected_index: int, seen: set[int]) -> bool:
        for index, call in enumerate(actual):
            if index in seen or not call_matches(call, expected[expected_index], case):
                continue
            seen.add(index)
            if index not in matched or augment(matched[index], seen):
                matched[index] = expected_index
                return True
        return False

    return sum(augment(index, set()) for index in range(len(expected)))


def tool_metrics(case: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, float]:
    expected = case["expectations"]["tool_call"]["required_calls"]
    optional = set(case["expectations"]["tool_call"]["allowed_extra_tools"])
    counted = [call for call in calls if call["name"] not in optional or any(item["name"] == call["name"] for item in expected)]
    matched = matched_call_count(counted, expected, case)
    precision = matched / len(counted) if counted else float(not expected)
    recall = matched / len(expected) if expected else 1.0
    valid = [
        call["name"] in TOOL_ARGUMENT_SCHEMAS
        and not list(Draft202012Validator(TOOL_ARGUMENT_SCHEMAS[call["name"]]).iter_errors(call["arguments"]))
        for call in calls
    ]
    return {
        "tool_name_and_hard_args_accuracy": float(matched == len(expected) == len(counted)),
        "tool_precision": precision, "tool_recall": recall,
        "tool_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "tool_argument_schema_valid": float(all(valid)),
    }


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


def plan_metrics(case: dict[str, Any], calls: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, float | None]:
    expected = case["expectations"]["plan"]
    if expected is None:
        return {}
    call = next((call for call in calls if call["name"] == ToolName.CREATE_PLAN), None)
    selected = call["arguments"].get("place_ids") if call else None
    metrics: dict[str, float | None] = {
        "selection_ids_valid": None, "required_places_included": None, "excluded_places_omitted": None,
        "selection_relevance_ratio": None,
        "selection_count_valid": None, "server_preserves_selected_ids": None,
        "schedule_within_window": None, "route_cost_ratio": None, "route_time_consistent": None,
    }
    if not isinstance(selected, list) or any(type(value) is not int for value in selected):
        if call is not None:
            metrics["selection_ids_valid"] = 0.0
        return metrics
    metrics.update({
        "selection_ids_valid": float(len(set(selected)) == len(selected) and set(selected) <= set(expected["allowed_place_ids"])),
        "required_places_included": float(set(expected["required_place_ids"]) <= set(selected)),
        "excluded_places_omitted": float(not set(selected).intersection(expected["exclude_place_ids"])),
        "selection_count_valid": float(expected["min_stops"] <= len(selected) <= expected["max_stops"]),
        "selection_relevance_ratio": len(set(selected).intersection(expected["relevant_place_ids"])) / len(set(selected)) if selected else 0.0,
    })
    if response.get("type") != ResponseType.PLAN or not isinstance(response.get("data"), dict):
        return metrics
    stops = response["data"].get("stops", [])
    ordered = [stop.get("placeId") for stop in stops if isinstance(stop, dict)]
    metrics["server_preserves_selected_ids"] = float(len(ordered) == len(selected) and set(ordered) == set(selected))
    matrix = case["fixtures"].get("travel_cost_matrix")
    if not matrix or not selected or len(selected) > 6 or not metrics["selection_ids_valid"] or not metrics["server_preserves_selected_ids"]:
        return metrics
    _, optimal = optimal_route(selected, matrix)
    cost = route_cost(ordered, matrix)
    metrics["route_cost_ratio"] = cost / optimal if optimal else 1.0
    clock = datetime.fromisoformat(expected["start_at"])
    previous = "origin"
    consistent = True
    for stop in stops:
        place_id = stop["placeId"]
        arrival = clock + timedelta(minutes=matrix["costs"][previous][str(place_id)])
        stay = expected["stay_minutes"][str(place_id)]
        departure = arrival + timedelta(minutes=stay)
        consistent &= stop.get("arrivalAt") == arrival.isoformat() and stop.get("departureAt") == departure.isoformat()
        clock = departure
        previous = str(place_id)
    metrics["route_time_consistent"] = float(consistent)
    metrics["schedule_within_window"] = float(clock <= datetime.fromisoformat(expected["end_at"]))
    return metrics


def state_metrics(case: dict[str, Any], record: dict[str, Any], response: dict[str, Any]) -> dict[str, float | None]:
    expected = case["expectations"]["state"]
    if expected is None:
        return {}
    data = response.get("data")
    values: dict[str, float | None] = {
        "preview_not_reported_as_applied": float(not data.get("applied")) if isinstance(data, dict) and "applied" in data and not expected["applied"] else None,
        "observed_plan_state_preserved": None,
        "observed_nonplan_memory_preserved": None,
        "confirmation_precedes_apply": float(case["input"].get("confirmed_event", {}).get("confirmed") is True) if isinstance(data, dict) and data.get("applied") else None,
        "observed_commit_version_matches": None,
    }
    observations = record.get("observations") or {}
    if not isinstance(observations, dict):
        return values
    if observations.get("source") != "backend_observation":
        return values
    if "plan_before" in observations and "plan_after" in observations and not expected["applied"]:
        values["observed_plan_state_preserved"] = float(observations["plan_before"] == observations["plan_after"])
    if expected["applied"] and isinstance(data, dict) and "plan_before" in observations and "plan_after" in observations:
        before = observations["plan_before"].get("version")
        after = observations["plan_after"].get("version")
        values["observed_commit_version_matches"] = float(type(before) is int and type(after) is int and after == before + 1 and after == data.get("version"))
    if case["expectations"]["memory"] and case["expectations"]["memory"].get("rollback_scope") == "plan_only":
        if "nonplan_before" in observations and "nonplan_after" in observations:
            values["observed_nonplan_memory_preserved"] = float(observations["nonplan_before"] == observations["nonplan_after"])
    return values


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
    memory = case["expectations"]["memory"]
    if memory and memory.get("relevant_memory_ids") and isinstance(record.get("memory_retrieval_ids"), list):
        metrics.update(ranking_metrics(record["memory_retrieval_ids"], {identifier: 3 for identifier in memory["relevant_memory_ids"]}, "memory_"))
    if memory:
        observations = record.get("observations") or {}
        metrics["inferred_memory_requires_confirmation"] = None
        metrics["explicit_preference_extraction_correct"] = None
        if isinstance(record.get("extracted_preferences"), list) and memory.get("explicit_preference"):
            metrics["explicit_preference_extraction_correct"] = float(any(
                fact.get("facet") == memory["explicit_preference"] and fact.get("basis") == "explicit"
                for fact in record["extracted_preferences"] if isinstance(fact, dict)
            ))
        if memory.get("inference_requires_confirmation") and isinstance(observations, dict) and observations.get("source") == "backend_observation" and observations.get("memory_job_completed"):
            metrics["inferred_memory_requires_confirmation"] = float(all(
                event.get("basis") != "inferred" or not event.get("persisted") or event.get("user_confirmed")
                for event in observations.get("memory_events", [])
            ))
    return {"metrics": metrics, "issues": issues}
