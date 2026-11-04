"""Authoritative metadata eligibility, before query encoding and vector comparison."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlaceMetadataFilter:
    conditions: tuple[str, ...]
    parameters: tuple[Any, ...]

    @classmethod
    def build(cls, filters: dict[str, Any], offset: int = 0) -> PlaceMetadataFilter:
        conditions = ["document_status = 'READY'", "source_version = latest_seen_version"]
        parameters: list[Any] = []
        for column in ("region", "city", "category"):
            value = filters.get(column)
            if value and value.strip():
                parameters.append(value)
                conditions.append(f"{column} = ${offset + len(parameters)}")
        if filters.get("exclude_place_ids"):
            parameters.append(filters["exclude_place_ids"])
            conditions.append(f"NOT (place_id = ANY(${offset + len(parameters)}::bigint[]))")
        area = filters.get("area")
        if area:
            center = area["center"]
            parameters.extend([center["lat"], center["lat"], center["lon"], area["radius_meters"]])
            latitude_a, latitude_b, longitude, radius = range(offset + len(parameters) - 3, offset + len(parameters) + 1)
            conditions.append(f"""latitude IS NOT NULL AND longitude IS NOT NULL
                AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180
                AND 6371000 * 2 * asin(sqrt(least(1.0,
                    power(sin(radians(latitude - ${latitude_a}) / 2), 2)
                    + cos(radians(${latitude_b})) * cos(radians(latitude))
                    * power(sin(radians(longitude - ${longitude}) / 2), 2)))) <= ${radius}""")
        return cls(tuple(conditions), tuple(parameters))

    async def execute(self, pool: Any) -> list[int]:
        query = "SELECT place_id FROM place_embeddings WHERE " + " AND ".join(self.conditions)
        async with pool.acquire() as connection:
            return [row["place_id"] for row in await connection.fetch(query, *self.parameters)]
