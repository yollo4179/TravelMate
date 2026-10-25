"""Check selected places and deterministic schedule constraints."""
from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta
from common.dataset.contracts import ResponseType, ToolName
from tracks.plan.score_route import optimal_route, route_cost


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
