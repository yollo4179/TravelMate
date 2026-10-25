"""Bounded open-path route checks from origin; no return trip or road times are invented."""
from __future__ import annotations

from itertools import permutations
from typing import Any


def route_cost(place_ids: list[int], matrix: dict[str, Any]) -> float:
    nodes = ["origin", *(str(place_id) for place_id in place_ids)]
    return sum(float(matrix["costs"][first][second]) for first, second in zip(nodes, nodes[1:]))


def optimal_route(place_ids: list[int], matrix: dict[str, Any]) -> tuple[list[int], float]:
    if not place_ids or len(place_ids) > 6 or len(set(place_ids)) != len(place_ids):
        raise ValueError("Route fixture requires 1..6 unique selected place IDs")
    order = min(permutations(place_ids), key=lambda sequence: (route_cost(list(sequence), matrix), sequence))
    return list(order), route_cost(list(order), matrix)
