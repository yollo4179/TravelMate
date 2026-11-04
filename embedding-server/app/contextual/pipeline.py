from __future__ import annotations

from typing import Any, Protocol

from app.enrichment.contracts import ExistingPlace, EvidenceStatus
from app.enrichment.evidence import searchable_claims
from .contracts import CaptureScope, PlaceRole, SearchChunk, SourceDocument, SourceType
from .contracts import SPLITTER_VERSION
from .splitting import split_document
# Re-exported so existing imports keep the same selection entry point.
from .selection import select_active  # noqa: F401


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


def split_source(source: SourceDocument, size: int = 800, *, splitter_version: str = SPLITTER_VERSION) -> list[tuple[int, int]]:
    return split_document(source, size, splitter_version)


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


def index_embedding_inputs(place: ExistingPlace, chunks: list[SearchChunk]) -> tuple[list[str], int]:
    """목적지의 기본 벡터가 출발지의 관찰 문장으로 바뀌지 않도록 한다."""
    texts = [chunk.embedding_text for chunk in chunks]
    subject_index = next((index for index, chunk in enumerate(chunks) if place.place_id in chunk.subject_place_ids), None)
    if subject_index is not None:
        return texts, subject_index
    texts.append(f"{place.name}. {place.description or ''}".strip())
    return texts, len(texts) - 1
