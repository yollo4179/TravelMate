from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math
from typing import Any


class CollectionStatus(StrEnum):
    PLANNED = "PLANNED"
    COLLECTED = "COLLECTED"
    FAILED = "FAILED"


class EvidenceStatus(StrEnum):
    EXCERPT_MATCHED = "PROVIDER_EXCERPT_MATCHED"
    UNVERIFIED = "UNVERIFIED"


class EntityMatch(StrEnum):
    MATCHED = "matched"
    UNRESOLVED = "unresolved"
    MISMATCH = "mismatch"


class Polarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


def fingerprint(document: Any) -> str:
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class ExistingPlace:
    place_id: int
    name: str
    description: str | None = None
    region: str | None = None
    city: str | None = None
    category: str | None = None
    source_category: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    tour_content_id: str | None = None
    image_url: str | None = None
    homepage_url: str | None = None

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> ExistingPlace:
        values = {key: row.get(key) for key in cls.__dataclass_fields__ if key != "place_id"}
        identifier = row.get("place_id", row.get("id"))
        if type(identifier) is not int or identifier <= 0 or not isinstance(values["name"], str) or not values["name"].strip():
            raise ValueError("Existing place requires a positive integer ID and a name")
        for key in ("latitude", "longitude"):
            if values[key] is not None:
                number = float(values[key])
                bound = 90 if key == "latitude" else 180
                if not math.isfinite(number) or not -bound <= number <= bound:
                    raise ValueError("Invalid existing place coordinate")
                values[key] = number
        for key, value in values.items():
            if key not in ("latitude", "longitude") and value is not None and not isinstance(value, str):
                raise ValueError(f"Invalid existing place field: {key}")
        return cls(place_id=identifier, **values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def source_fingerprint(self) -> str:
        return fingerprint(self.to_dict())


EVIDENCE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["url", "quote"],
    "properties": {"url": {"type": "string", "minLength": 1}, "quote": {"type": "string", "minLength": 1}},
}
CLAIM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["aspect", "statement", "polarity", "conditions", "evidence"],
    "properties": {
        "aspect": {"type": "string", "minLength": 1},
        "statement": {"type": "string", "minLength": 1},
        "polarity": {"type": "string", "enum": [value.value for value in Polarity]},
        "conditions": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "minItems": 1, "items": EVIDENCE_SCHEMA},
    },
}
ENRICHMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["place_id", "entity_match", "claims", "conflicts", "unknowns"],
    "properties": {
        "place_id": {"type": "integer", "minimum": 1},
        "entity_match": {"type": "string", "enum": [value.value for value in EntityMatch]},
        "claims": {"type": "array", "items": CLAIM_SCHEMA},
        "conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["aspect", "reason"],
            "properties": {"aspect": {"type": "string", "minLength": 1}, "reason": {"type": "string", "minLength": 1}},
        }},
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
}
