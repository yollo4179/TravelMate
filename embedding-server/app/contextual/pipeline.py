from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Protocol

from app.enrichment.contracts import ExistingPlace, EvidenceStatus
from app.enrichment.evidence import searchable_claims
from .contracts import CaptureScope, MAX_ACTIVE_CHUNKS, PlaceRole, SearchChunk, SourceDocument, SourceType


class SourceStrategy(Protocol):
    def is_applicable(self, source: dict[str, Any]) -> bool: ...
    def normalize(self, source: dict[str, Any]) -> SourceDocument: ...


class TourApiStrategy:
    def is_applicable(self, source: dict[str, Any]) -> bool:
        return source.get("source_type") == SourceType.TOURAPI

    def normalize(self, source: dict[str, Any]) -> SourceDocument:
        return SourceDocument.from_mapping(source)


class AccountStrategy:
    def is_applicable(self, source: dict[str, Any]) -> bool:
        return source.get("source_type") in (SourceType.BLOG, SourceType.REVIEW, SourceType.WEB)

    def normalize(self, source: dict[str, Any]) -> SourceDocument:
        return SourceDocument.from_mapping(source)


SOURCE_STRATEGIES: tuple[SourceStrategy, ...] = (TourApiStrategy(), AccountStrategy())


def normalize_source(source: dict[str, Any]) -> SourceDocument:
    matches = [strategy for strategy in SOURCE_STRATEGIES if strategy.is_applicable(source)]
    if len(matches) != 1:
        raise ValueError("Exactly one source strategy must match")
    return matches[0].normalize(source)


def split_source(source: SourceDocument, size: int = 800) -> list[tuple[int, int]]:
    if size < 1:
        raise ValueError("Chunk size must be positive")
    spans = []
    start = 0
    while start < len(source.text):
        end = min(start + size, len(source.text))
        if end < len(source.text):
            boundary = max(source.text.rfind("\n", start + size // 2, end), source.text.rfind(". ", start + size // 2, end))
            if boundary > start:
                end = boundary + 1
        if source.text[start:end].strip():
            spans.append((start, end))
        start = end
    return spans


def tourapi_chunks(place: ExistingPlace) -> list[SearchChunk]:
    if not place.description or not place.description.strip():
        return []
    source = normalize_source({
        "source_type": SourceType.TOURAPI, "title": place.name, "text": place.description,
        "metadata": {"tour_content_id": place.tour_content_id or f"place:{place.place_id}",
                     "field": "description", "capture_scope": CaptureScope.FIELD,
                     "place_fingerprint": place.source_fingerprint},
    })
    return [SearchChunk(source, start, end, f"{place.name}. TourAPI 장소 설명의 일부이다.",
                        [{"place_id": place.place_id, "role": PlaceRole.SUBJECT}],
                        {"provider": "template", "model": None, "prompt_version": "tourapi-context-v1"})
            for start, end in split_source(source)]


def legacy_evidence_chunks(place: ExistingPlace, snapshot: dict[str, Any] | None) -> list[SearchChunk]:
    if snapshot is None:
        return []
    document = snapshot["document"]
    chunks = []
    for claim in searchable_claims(document):
        for evidence in claim["evidence"]:
            if evidence["status"] != EvidenceStatus.EXCERPT_MATCHED:
                continue
            quote = " ".join(evidence["quote"].split())
            matching = [source for source in document["sources"]
                        if source["url"] == evidence["url"] and quote in " ".join(source["snippet"].split())]
            if not matching:
                continue
            original = matching[0]
            source = normalize_source({
                "source_type": SourceType.WEB, "title": original.get("title") or place.name,
                "text": " ".join(original["snippet"].split()),
                "metadata": {"source_url": original["url"], "capture_scope": CaptureScope.EXCERPT,
                             "published_at": original.get("published_at"), "raw_excerpt": original["snippet"],
                             "normalization": "whitespace-v1"},
            })
            start = source.text.index(quote)
            context = f"{place.name} 관련 웹 자료의 관찰·후기. {claim['statement']}"
            if claim["conditions"]:
                context += " (조건: " + " / ".join(claim["conditions"]) + ")"
            chunks.append(SearchChunk(source, start, start + len(quote), context[:600],
                                      [{"place_id": place.place_id, "role": PlaceRole.SUBJECT}],
                                      {"provider": "perplexity", "model": snapshot.get("actual_model"),
                                       "prompt_version": snapshot.get("prompt_version", "existing-place-evidence-v1"),
                                       "snapshot_id": str(snapshot["snapshot_id"]), "scope": "provider_excerpt_matched"}))
    return chunks


def select_active(place_id: int, chunks: list[SearchChunk]) -> list[SearchChunk]:
    """Round-robin sources; duplicate text cannot consume multiple place slots."""
    groups: dict[str, deque[SearchChunk]] = defaultdict(deque)
    seen = set()
    for chunk in chunks:
        if not any(ref["place_id"] == place_id and ref["role"] == PlaceRole.SUBJECT for ref in chunk.place_refs):
            continue
        key = " ".join(chunk.chunk_text.split())
        if key in seen:
            continue
        seen.add(key)
        groups[chunk.source.source_id].append(chunk)
    active = []
    while groups and len(active) < MAX_ACTIVE_CHUNKS:
        for source_id in list(groups):
            active.append(groups[source_id].popleft())
            if not groups[source_id]:
                del groups[source_id]
            if len(active) == MAX_ACTIVE_CHUNKS:
                break
    return active
