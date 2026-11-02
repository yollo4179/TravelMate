"""Offline contract proposal projection, not an application adapter or search implementation."""
from __future__ import annotations

from typing import Any


def proposed_search_request(case: dict[str, Any]) -> dict[str, Any]:
    conditions = case["input"].get("conditions") or {}
    supported = {"region", "city", "category", "area", "exclude_place_ids", "conversation"}
    if any(value not in (None, [], {}, "") for key, value in conditions.items() if key not in supported):
        raise ValueError("Unmapped search condition; do not silently weaken the case")
    area = conditions.get("area")
    mapped_area = None
    if area is not None:
        if area.get("distance_method") != "haversine_straight_line":
            raise ValueError("Unverified distance semantics")
        center = area["center"]
        mapped_area = {"type": "CIRCLE", "center": {"lat": center["latitude"], "lon": center["longitude"]},
                       "radiusMeters": area["radius_meters"]}
    return {"query": case["input"]["query"], "region": conditions.get("region"), "city": conditions.get("city"),
            "category": conditions.get("category"), "excludePlaceIds": conditions.get("exclude_place_ids") or [],
            "area": mapped_area, "limit": 10, "rankingMode": "RERANKED"}


def search_case_mapping(case: dict[str, Any], input_sha256: str) -> dict[str, Any]:
    request = proposed_search_request(case)
    conditions = case["input"]["conditions"]
    messages = case["input"].get("messages") or []
    historical = conditions.get("conversation") or []
    if messages and historical and messages != historical:
        raise ValueError("Conflicting history sources; no silent replacement or duplication")
    return {"case_id": case["case_id"], "split": case["split"], "input_sha256": input_sha256,
            "original_conditions": conditions, "proposed_search_request": request,
            "conversation_history_once": messages or historical,
            "current_get_filter_transport_supported": not request["excludePlaceIds"] and request["area"] is None,
            "current_llm_tool_works_without_plan": False,
            "proposed_contract_can_represent_search_filters": True,
            "application_adapter_implemented": False, "search_executed": False,
            "runtime_corpus_verified": False,
            "area_provenance": area_provenance(conditions.get("area"))}


def area_provenance(area: dict[str, Any] | None) -> dict[str, Any] | None:
    if area is None:
        return None
    return {"center_place_id": area.get("center_place_id"), "distance_method": area.get("distance_method"),
            "meaning": "spatial anchor and straight-line radius; not mandatory visit or walk-time evidence"}
