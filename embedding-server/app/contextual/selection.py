"""Active chunk selection per place, as versioned strategies chosen by configuration."""
from __future__ import annotations

from collections import defaultdict, deque
from enum import StrEnum
from typing import Protocol

from .contracts import MAX_ACTIVE_CHUNKS, SearchChunk, SourceType
from .excerpts import ChunkAspect, ReviewedExcerptModule


class ActiveSelectionVersion(StrEnum):
        # 기존 동작: 출처별로 돌아가며 최대 20개를 고른다.
        SOURCE_ROUND_ROBIN_V1 = "source-round-robin-v1"
        # 관점(주차·후기·설명·체험)별로 먼저 돌아가고, 같은 관점 안에서는 출처별로 돌아간다.
        ASPECT_ROUND_ROBIN_V2 = "aspect-source-round-robin-v2"


DEFAULT_ACTIVE_SELECTION = ActiveSelectionVersion.SOURCE_ROUND_ROBIN_V1


class AspectRule(Protocol):
    def is_applicable(self, chunk: SearchChunk) -> bool: ...
    def aspect(self, chunk: SearchChunk) -> ChunkAspect: ...


def _is_reviewed_excerpt(chunk: SearchChunk) -> bool:
    return chunk.generation.get("provider") == ReviewedExcerptModule.PROVIDER


class ReviewedExcerptAspect:
    def is_applicable(self, chunk: SearchChunk) -> bool:
        return _is_reviewed_excerpt(chunk)

    def aspect(self, chunk: SearchChunk) -> ChunkAspect:
        return ChunkAspect(chunk.generation["aspect"])


class TourApiDescriptionAspect:
    def is_applicable(self, chunk: SearchChunk) -> bool:
        # A reviewer may quote TourAPI text as parking or experience; the reviewed aspect outranks the source default.
        return chunk.source.source_type == SourceType.TOURAPI and not _is_reviewed_excerpt(chunk)

    def aspect(self, chunk: SearchChunk) -> ChunkAspect:
        return ChunkAspect.DESCRIPTION


# Only provenance decides the aspect. Generated contextual chunks stay unclassified rather than keyword-guessed.
ASPECT_RULES: tuple[AspectRule, ...] = (ReviewedExcerptAspect(), TourApiDescriptionAspect())


def chunk_aspect(chunk: SearchChunk) -> ChunkAspect | None:
    matches = [rule for rule in ASPECT_RULES if rule.is_applicable(chunk)]
    if len(matches) > 1:
        raise ValueError("At most one aspect rule may match a chunk")
    return matches[0].aspect(chunk) if matches else None


def _unique_for_place(place_id: int, chunks: list[SearchChunk]) -> list[SearchChunk]:
    seen = set()
    unique = []
    for chunk in chunks:
        key = " ".join(chunk.chunk_text.split())
        if place_id not in chunk.index_place_ids or key in seen:
            continue
        seen.add(key)
        unique.append(chunk)
    return unique


def _round_robin(groups: dict[object, deque[SearchChunk]], limit: int) -> list[SearchChunk]:
    selected = []
    while groups and len(selected) < limit:
        for key in list(groups):
            selected.append(groups[key].popleft())
            if not groups[key]:
                del groups[key]
            if len(selected) == limit:
                break
    return selected


def _by_source(chunks: list[SearchChunk]) -> dict[object, deque[SearchChunk]]:
    groups: dict[object, deque[SearchChunk]] = defaultdict(deque)
    for chunk in chunks:
        groups[chunk.source.source_id].append(chunk)
    return groups


class SourceRoundRobinV1:
    def supports(self, version: ActiveSelectionVersion) -> bool:
        return version == ActiveSelectionVersion.SOURCE_ROUND_ROBIN_V1

    def execute(self, place_id: int, chunks: list[SearchChunk]) -> list[SearchChunk]:
        """Round-robin sources; duplicate text cannot consume multiple place slots."""
        return _round_robin(_by_source(_unique_for_place(place_id, chunks)), MAX_ACTIVE_CHUNKS)


class AspectRoundRobinV2:
    def supports(self, version: ActiveSelectionVersion) -> bool:
        return version == ActiveSelectionVersion.ASPECT_ROUND_ROBIN_V2

    def execute(self, place_id: int, chunks: list[SearchChunk]) -> list[SearchChunk]:
        # One aspect (e.g. many parking lines) cannot fill all twenty slots while others are available.
        by_aspect: dict[ChunkAspect | None, list[SearchChunk]] = defaultdict(list)
        for chunk in _unique_for_place(place_id, chunks):
            by_aspect[chunk_aspect(chunk)].append(chunk)
        ordered = [*(aspect for aspect in ChunkAspect if aspect in by_aspect), *([None] if None in by_aspect else [])]
        streams = {aspect: deque(_round_robin(_by_source(by_aspect[aspect]), len(by_aspect[aspect]))) for aspect in ordered}
        return _round_robin(streams, MAX_ACTIVE_CHUNKS)


ACTIVE_SELECTIONS = (SourceRoundRobinV1(), AspectRoundRobinV2())


def select_active(
    place_id: int,
    chunks: list[SearchChunk],
    version: ActiveSelectionVersion = DEFAULT_ACTIVE_SELECTION,
) -> list[SearchChunk]:
    matches = [strategy for strategy in ACTIVE_SELECTIONS if strategy.supports(ActiveSelectionVersion(version))]
    if len(matches) != 1:
        raise ValueError("Exactly one active selection strategy must match")
    return matches[0].execute(place_id, chunks)
