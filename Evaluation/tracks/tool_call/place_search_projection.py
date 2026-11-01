"""Explicit v2-to-frozen scoring view. Never rewrites the observed native tool call."""
from __future__ import annotations

import json
from typing import Any


def project_search_call(call: dict[str, Any], model_result: dict[str, Any]) -> dict[str, Any] | None:
    if call["function"]["name"] != "search_places" or model_result.get("searchContractVersion") != "place-search-v2":
        return None
    native_arguments = json.loads(call["function"]["arguments"])
    effective = model_result["searchCriteria"]
    if native_arguments["query"] != effective["query"]:
        raise ValueError("Search query provenance mismatch")
    area = effective.get("area")
    projected_area = None if area is None else {
        "type": "circle", "center": {"latitude": area["center"]["lat"], "longitude": area["center"]["lon"]},
        "radius_meters": area["radiusMeters"],
    }
    arguments = {"query": effective["query"], "region": effective.get("region"), "city": effective.get("city"),
                 "exclude_place_ids": effective["excludePlaceIds"], "area": projected_area}
    # The legacy schema has optional fields, not nullable properties.
    arguments = {name: value for name, value in arguments.items() if value is not None}
    return {"projection_version": "place-search-v2-to-frozen-v1", "native_call_id": call["id"],
            "native_arguments": native_arguments, "effective_search_criteria": effective,
            "filter_provenance": model_result.get("filterProvenance"),
            "projected_tool_call": {"id": call["id"], "type": "function", "function": {
                "name": "search_places", "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))}},
            "server_settings_outside_frozen_arguments": {"limit": effective["limit"], "rankingMode": effective["rankingMode"]},
            "unrepresented_conditions": ["category"] if effective.get("category") is not None else [],
            "status": "PROJECTED_NOT_SCORED", "legacy_exact_args_automatically_accepted": False}


def conditions_covered(expected: dict[str, Any], criteria: dict[str, Any]) -> bool:
    supported = {"region", "city", "category", "exclude_place_ids", "area", "conversation"}
    if any(value not in (None, [], "", {}) for key, value in expected.items() if key not in supported):
        return False
    if any(expected.get(field) != criteria.get(field) for field in ("region", "city", "category")):
        return False
    if set(expected.get("exclude_place_ids") or []) != set(criteria.get("excludePlaceIds") or []):
        return False
    area = expected.get("area")
    actual = criteria.get("area")
    if not area:
        return actual is None
    return (actual is not None and str(area.get("type", "circle")).lower() == "circle"
            and area.get("distance_method") == "haversine_straight_line"
            and actual["type"] == "CIRCLE" and actual["center"] == {
                "lat": area["center"]["latitude"], "lon": area["center"]["longitude"]}
            and actual["radiusMeters"] == area["radius_meters"])


def history_covered(model_input: dict[str, Any], request: dict[str, Any]) -> bool:
    messages = model_input.get("messages") or []
    conversation = (model_input.get("conditions") or {}).get("conversation") or []
    if messages and conversation and messages != conversation:
        return False
    expected = messages or conversation
    actual = request.get("history") or []
    return [{"role": item["role"].lower(), "content": item["content"]} for item in actual] == expected
