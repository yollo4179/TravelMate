"""원문·관찰·독립 관계를 조합하는 검색 계약 검증용 입력."""
from __future__ import annotations

from typing import Any

from app.contextual.contracts import CaptureScope, ContentKind, MovementCondition, PlaceRole, SearchChunk, SourceType, SplitterVersion
from app.contextual.pipeline import normalize_source
from app.contextual.relations import RelationImportance, RelationType
from app.enrichment.contracts import fingerprint

WALK = "출발공원에서 계단을 내려가 도착공원까지 걸어갔다."
BLOCK = "출발공원에서 도착공원으로 이동하려 했지만 공사로 길이 막혀 돌아왔다."
VEHICLE = "도착공원까지 차량으로만 이동할 수 있으며 도보 통행은 금지된다."


def document(
    quote: str,
    *,
    origin: int = 901,
    destination: int = 902,
    importance: RelationImportance = RelationImportance.PRIMARY,
    conditions: tuple[str, ...] = (),
    relation: bool = True,
    movement_quote: str | None = None,
    kind: ContentKind = ContentKind.OTHER,
) -> dict[str, Any]:
    source = normalize_source({
        "source_type": SourceType.REVIEW,
        "title": "원문 보존 검사",
        "text": quote,
        "metadata": {
            "source_url": "https://example.org/quality/" + fingerprint([quote, origin, destination]),
            "capture_scope": CaptureScope.FULL,
        },
    })
    relation_quote = movement_quote if movement_quote is not None else quote
    start = quote.index(relation_quote)
    relations = [{
        "type": RelationType.MOVEMENT,
        "importance": importance,
        "origin": {"place_id": origin, "name": "출발공원"},
        "destination": {"place_id": destination, "name": "도착공원"},
        "conditions": [{"kind": MovementCondition.OTHER, "quote": condition} for condition in conditions],
        "evidence": {"start": start, "end": start + len(relation_quote), "quote": relation_quote},
    }] if relation else []
    chunk = SearchChunk(
        source=source,
        start=0,
        end=len(quote),
        context_text="관찰과 관계의 원문을 보존한 검사용 기록이다.",
        place_refs=[{"place_id": origin, "role": PlaceRole.SUBJECT}, {"place_id": destination, "role": PlaceRole.MENTIONED}],
        generation={"provider": "synthetic-search-contract"},
        splitter_version=SplitterVersion.SENTENCE,
        content_kind=kind,
        relations=relations,
    )
    return {**chunk.to_dict(), "context_version": chunk.context_version, "metadata": source.metadata}


def candidate(
    place_id: int,
    documents: list[dict[str, Any]],
    scores: list[float],
) -> dict[str, Any]:
    return {
        "place_id": place_id,
        "source_version": 7,
        "semantic_score": 0.1,
        "description": documents[0]["chunk_text"],
        "evidence": documents[0],
        "reranked_evidence_chunks": [
            {**entry, "rerank_score": score, "semantic_score": 0.1}
            for entry, score in zip(documents, scores, strict=True)
        ],
    }
