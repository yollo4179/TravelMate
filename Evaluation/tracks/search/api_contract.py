"""Project frozen search inputs into the independent server contract without guessing."""
from __future__ import annotations

from enum import StrEnum
import math
from typing import Any


class RankingMode(StrEnum):
    SEMANTIC_ONLY = "SEMANTIC_ONLY"
    RERANKED = "RERANKED"


SUPPORTED_CONDITIONS = frozenset({"region", "city", "category", "exclude_place_ids", "area"})


def unsupported_conditions(conditions: dict[str, Any]) -> list[str]:
    return [name for name, value in conditions.items() if name not in SUPPORTED_CONDITIONS and value not in (None, [], {}, "")]


def search_body(case: dict[str, Any], mode: RankingMode, limit: int) -> dict[str, Any]:
    query = case["input"]["query"]
    conditions = case["input"]["conditions"]
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("The original nonblank query must fit the server contract; it is never guessed or shortened")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("The explicit response limit must be within 1..20")
    return {"query": query, "limit": limit, "rankingMode": mode.value, **search_filters(conditions)}


def search_filters(conditions: dict[str, Any]) -> dict[str, Any]:
    """Share only filter projection with conversation; message length is a different contract."""
    body: dict[str, Any] = {}
    for name in ("region", "city", "category"):
        value = conditions.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 200):
            raise ValueError(f"Invalid original {name} filter")
        body[name] = value
    excluded = conditions.get("exclude_place_ids") or []
    if not isinstance(excluded, list) or any(type(identifier) is not int or identifier <= 0 for identifier in excluded):
        raise ValueError("Excluded place IDs must be positive integers")
    if len(set(excluded)) != len(excluded):
        raise ValueError("Duplicate excluded IDs are rejected, not silently removed")
    body["excludePlaceIds"] = excluded
    body["area"] = None
    area = conditions.get("area")
    if area is None:
        return body
    # The center ID identifies coordinate provenance; only explicit coordinates reach the server.
    allowed = {"type", "center", "center_place_id", "radius_meters", "distance_method"}
    if set(area) - allowed or str(area.get("type", "circle")).lower() != "circle":
        raise ValueError("Only the explicit frozen circular area is representable")
    if area.get("distance_method") not in (None, "haversine_straight_line"):
        raise ValueError("Walking or driving distance is not a coordinate-radius filter")
    center = area["center"]
    if set(center) != {"latitude", "longitude"}:
        raise ValueError("Unexpected area center fields")
    for name, bound in (("latitude", 90), ("longitude", 180)):
        value = center[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not -bound <= value <= bound:
            raise ValueError("Invalid area coordinates")
    radius = area["radius_meters"]
    if type(radius) is not int or not 500 <= radius <= 10000:
        raise ValueError("The server supports radiusMeters within 500..10000")
    body["area"] = {"type": "CIRCLE", "center": {"lat": center["latitude"], "lon": center["longitude"]}, "radiusMeters": radius}
    return body
