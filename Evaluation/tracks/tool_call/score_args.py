"""Score tool selection, schemas and hard arguments from recorded calls."""
from __future__ import annotations

from typing import Any
import json
from jsonschema import Draft202012Validator
from common.dataset.contracts import TOOL_ARGUMENT_SCHEMAS


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
