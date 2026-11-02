"""Preserved description fields attached after place retrieval; never chunk embeddings."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any
import uuid

from app.enrichment.contracts import ExistingPlace, fingerprint
from .contracts import CaptureScope, NAMESPACE, PlaceRole, SourceType
from .pipeline import normalize_source
from .relation_vectors import RetrievalPath


class OriginalEvidenceMode(StrEnum):
    DISABLED = "disabled"
    POST_RETRIEVAL = "post-retrieval-field-v1"


class VectorBinding(StrEnum):
    NONE = "NOT_EMBEDDED"


class SemanticScoreScope(StrEnum):
    PLACE_CANDIDATE = "place_candidate"


@dataclass(frozen=True)
class FrozenSnapshot:
    version: str
    snapshot_sha256: str
    corpus_sha256: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        if not self.version or any(len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
                                   for value in (self.snapshot_sha256, self.corpus_sha256, self.manifest_sha256)):
            raise ValueError("Frozen field evidence requires exact snapshot/corpus/manifest bindings")


def description_evidence(place: ExistingPlace, snapshot: FrozenSnapshot) -> dict[str, Any]:
    if not place.tour_content_id or not place.description or not place.description.strip():
        raise ValueError("A preserved TourAPI description and real content ID are required")
    original = place.description
    metadata = {
        "capture_scope": CaptureScope.FIELD, "field": "places.description",
        "origin": "frozen_corpus", "snapshot_version": snapshot.version,
        "snapshot_sha256": snapshot.snapshot_sha256, "corpus_sha256": snapshot.corpus_sha256,
        "dataset_manifest_sha256": snapshot.manifest_sha256,
        "place_id": place.place_id, "tour_content_id": place.tour_content_id,
        "place_fingerprint": place.source_fingerprint,
        "content_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
    }
    source = normalize_source({"source_type": SourceType.TOURAPI, "title": place.name,
                               "text": original, "metadata": metadata})
    document = {
        "chunk_id": str(uuid.uuid5(NAMESPACE, f"frozen-field:{snapshot.corpus_sha256}:{place.place_id}:{source.source_version}")),
        "source_id": source.source_id, "source_version": source.source_version,
        "source_type": source.source_type, "title": source.title, "chunk_text": original,
        "source_span": {"start": 0, "end": len(original), "unit": "unicode_codepoint"},
        "place_refs": [{"place_id": place.place_id, "role": PlaceRole.SUBJECT}],
        "metadata": metadata, "search_text": original,
        "retrieval_path": RetrievalPath.ORIGINAL_FIELD, "vector_binding": VectorBinding.NONE,
        "semantic_score_scope": SemanticScoreScope.PLACE_CANDIDATE,
    }
    return {**document, "context_version": fingerprint(document)}


def validate_description_evidence(document: dict[str, Any], place: ExistingPlace) -> None:
    metadata = document["metadata"]
    snapshot = FrozenSnapshot(metadata["snapshot_version"], metadata["snapshot_sha256"],
                              metadata["corpus_sha256"], metadata["dataset_manifest_sha256"])
    if description_evidence(place, snapshot) != document:
        raise ValueError("Original field evidence differs from preserved text, ownership or provenance")


async def attach_original_fields(pool: Any, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identifiers = sorted({row["place_id"] for row in candidates if row.get("evidence") is None})
    if not identifiers:
        return candidates
    records = await pool.fetch(
        """SELECT e.place_id, e.document, e.place_fingerprint, to_jsonb(p) AS current_place
        FROM place_original_field_evidence e JOIN place_embeddings p USING(place_id)
        WHERE e.place_id=ANY($1::bigint[]) AND p.document_status='READY'
          AND p.source_version=p.latest_seen_version AND p.source_version=e.place_source_version
          AND e.document->>'chunk_text'=p.description
          AND e.document->'metadata'->>'tour_content_id'=p.tour_content_id""",
        identifiers,
    )
    originals = {}
    for record in records:
        current = record["current_place"]
        place = ExistingPlace.from_mapping(json.loads(current) if isinstance(current, str) else current)
        if place.source_fingerprint != record["place_fingerprint"]:
            continue
        document = record["document"]
        document = json.loads(document) if isinstance(document, str) else document
        validate_description_evidence(document, place)
        originals[place.place_id] = document
    return [{**row, "evidence": originals[row["place_id"]]} if row.get("evidence") is None and row["place_id"] in originals
            else row for row in candidates]
