"""Kafka result serialization independent of inference model initialization."""
from __future__ import annotations

from enum import StrEnum
import json
from typing import Any


class EvidenceAssessmentStatus(StrEnum):
    NOT_ASSESSED = "not_assessed"


def result_item(candidate: dict[str, Any], rank: int, rerank_score: float | None) -> dict[str, Any]:
    evidence_chunks = candidate.get("reranked_evidence_chunks")
    if evidence_chunks is None:
        evidence = candidate.get("evidence")
        evidence_chunks = [json.loads(evidence) if isinstance(evidence, str) else evidence] if evidence else []
    return {
        "place_id": candidate["place_id"], "rank": rank, "name": candidate["name"],
        "description": candidate["description"], "region": candidate["region"], "city": candidate["city"],
        "category": candidate["category"], "source_category": candidate["source_category"],
        "latitude": candidate["latitude"], "longitude": candidate["longitude"],
        "tour_content_id": candidate["tour_content_id"], "image_url": candidate["image_url"],
        "homepage_url": candidate["homepage_url"], "semantic_score": candidate["semantic_score"],
        "rerank_score": rerank_score, "source_version": candidate["source_version"],
        "latest_seen_version": candidate["latest_seen_version"],
        "index_config_version": candidate.get("index_config_version", "bge-m3-v1"),
        "enrichment_snapshot_id": str(candidate["enrichment_snapshot_id"]) if candidate.get("enrichment_snapshot_id") else None,
        "evidence_chunks": evidence_chunks,
        "evidence_assessment": {"status": EvidenceAssessmentStatus.NOT_ASSESSED},
    }
