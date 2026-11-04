"""Optional reviewed excerpt intake. No keyword classifier or new generated facts."""
from __future__ import annotations
from dataclasses import dataclass
import copy
from enum import StrEnum
from typing import Any
from .contracts import SearchChunk, SourceDocument, PlaceRole


class ChunkAspect(StrEnum):
        # What the excerpt describes, independent of which place owns the statement.
        PARKING = "parking"
        REVIEW = "review_impression"
        DESCRIPTION = "place_description"
        EXPERIENCE = "experience"


class RelationCertainty(StrEnum):
        EXPLICIT_REVIEWED = "explicit_reviewed"
        AMBIGUOUS = "ambiguous"
        NOT_REVIEWED = "not_reviewed"


@dataclass(frozen=True)
class ExcerptInput:
    quote: str
    subject_place_id: int
    aspect: ChunkAspect
    context: str
    relations: tuple[dict[str, Any], ...] = ()
    relation_certainty: RelationCertainty = RelationCertainty.NOT_REVIEWED
    reviewer: str | None = None


@dataclass(frozen=True)
class ExcerptResult:
    chunks: tuple[SearchChunk, ...]
    held_relations: tuple[dict[str, Any], ...]
    held_excerpts: tuple[dict[str, Any], ...] = ()


class ExcerptHoldReason(StrEnum):
        RELATION_CLARITY_NOT_VERIFIED = "relation_clarity_not_verified"


class ExcerptVersion(StrEnum):
        REVIEWED_V1 = "reviewed-excerpts-v1"


class ReviewedExcerptModule:
    def supports(self, version: ExcerptVersion) -> bool:
        return version == ExcerptVersion.REVIEWED_V1

    def execute(self, source: SourceDocument, excerpts: list[ExcerptInput]) -> ExcerptResult:
        chunks = []
        held = []
        held_excerpts = []
        for excerpt in excerpts:
            if excerpt.relations and (excerpt.relation_certainty != RelationCertainty.EXPLICIT_REVIEWED or not excerpt.reviewer):
                held.extend(excerpt.relations)
                held_excerpts.append({"source_id": source.source_id, "quote": excerpt.quote,
                                      "reason": ExcerptHoldReason.RELATION_CLARITY_NOT_VERIFIED.value})
                continue
            accepted = copy.deepcopy(excerpt.relations) if excerpt.relation_certainty == RelationCertainty.EXPLICIT_REVIEWED and excerpt.reviewer else ()
            # Exact, unique server lookup; never accept numeric offsets supplied by a model.
            if not excerpt.quote or source.text.count(excerpt.quote) != 1:
                raise ValueError("An excerpt requires a unique exact quotation of the preserved source")
            start = source.text.index(excerpt.quote)
            for relation in accepted:
                quote = relation["evidence"]["quote"]
                if not quote or excerpt.quote.count(quote) != 1:
                    raise ValueError("A relation needs unique, exact evidence within its own excerpt")
                left = start + excerpt.quote.index(quote)
                relation["evidence"] = {"quote": quote, "start": left, "end": left + len(quote)}
            refs = [{"place_id": excerpt.subject_place_id, "role": PlaceRole.SUBJECT}]
            for relation in accepted:
                for endpoint in (relation["origin"], relation["destination"]):
                    if endpoint["place_id"] is not None and all(ref["place_id"] != endpoint["place_id"] for ref in refs):
                        refs.append({"place_id": endpoint["place_id"], "role": PlaceRole.MENTIONED})
            # Relations must already satisfy the independently validated exact-span contract.
            chunks.append(SearchChunk(source, start, start + len(excerpt.quote), excerpt.context,
                refs, {"provider": "reviewed-excerpt", "reviewer": excerpt.reviewer, "aspect": excerpt.aspect.value},
                content_kind="other", relations=list(accepted)))
        return ExcerptResult(tuple(chunks), tuple(held), tuple(held_excerpts))
