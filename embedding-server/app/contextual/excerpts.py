"""Optional reviewed excerpt intake. No keyword classifier or new generated facts."""
from __future__ import annotations
from dataclasses import dataclass
import copy
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from .contracts import ContentKind, SearchChunk, SourceDocument, PlaceRole


class ChunkAspect(StrEnum):
        # What the excerpt describes, independent of which place owns the statement.
        PARKING = "parking"                   # 주차 가능 여부·위치·요금
        REVIEW = "review_impression"          # 방문 후기·감상
        DESCRIPTION = "place_description"     # 장소 자체의 설명
        EXPERIENCE = "experience"             # 그곳에서 한 체험·활동

        @property
        def label(self) -> str:
            return ASPECT_LABELS[self]


# The label is embedded with the excerpt so each aspect forms its own region of the vector space.
ASPECT_LABELS = MappingProxyType({
    ChunkAspect.PARKING: "주차",
    ChunkAspect.REVIEW: "후기·감상",
    ChunkAspect.DESCRIPTION: "장소 설명",
    ChunkAspect.EXPERIENCE: "체험",
})


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
class ExcerptConfig:
    # 요구 사항: 판단 근거는 2~3줄. 한국어 한 줄을 약 60~70자로 보고 상한을 둔다.
    max_quote_characters: int = 200
    context_characters: int = 600


@dataclass(frozen=True)
class ExcerptResult:
    chunks: tuple[SearchChunk, ...]
    held_relations: tuple[dict[str, Any], ...]
    held_excerpts: tuple[dict[str, Any], ...] = ()


class ExcerptHoldReason(StrEnum):
        RELATION_CLARITY_NOT_VERIFIED = "relation_clarity_not_verified"
        QUOTE_TOO_LONG = "quote_longer_than_two_or_three_lines"


class ExcerptVersion(StrEnum):
        REVIEWED_V1 = "reviewed-excerpts-v1"


class ReviewedExcerptModule:
    PROVIDER = "reviewed-excerpt"

    def supports(self, version: ExcerptVersion) -> bool:
        return version == ExcerptVersion.REVIEWED_V1

    def execute(
        self,
        source: SourceDocument,
        excerpts: list[ExcerptInput],
        config: ExcerptConfig = ExcerptConfig(),
    ) -> ExcerptResult:
        chunks = []
        held = []
        held_excerpts = []
        for excerpt in excerpts:
            if excerpt.relations and (excerpt.relation_certainty != RelationCertainty.EXPLICIT_REVIEWED or not excerpt.reviewer):
                held.extend(excerpt.relations)
                held_excerpts.append({"source_id": source.source_id, "quote": excerpt.quote,
                                      "reason": ExcerptHoldReason.RELATION_CLARITY_NOT_VERIFIED.value})
                continue
            # A long passage mixes several judgments; the reviewer splits it instead of the server truncating it.
            if len(excerpt.quote) > config.max_quote_characters:
                held_excerpts.append({"source_id": source.source_id, "quote": excerpt.quote,
                                      "reason": ExcerptHoldReason.QUOTE_TOO_LONG.value})
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
            context = f"[{excerpt.aspect.label}] {excerpt.context}"[:config.context_characters]
            # Relations must already satisfy the independently validated exact-span contract.
            chunks.append(SearchChunk(
                source,
                start,
                start + len(excerpt.quote),
                context,
                refs,
                {"provider": self.PROVIDER, "reviewer": excerpt.reviewer, "aspect": excerpt.aspect.value},
                content_kind=ContentKind.OTHER.value,
                relations=list(accepted),
            ))
        return ExcerptResult(tuple(chunks), tuple(held), tuple(held_excerpts))


EXCERPT_MODULES = (ReviewedExcerptModule(),)


@dataclass(frozen=True)
class ExcerptIntake:
    version: ExcerptVersion
    source: SourceDocument
    excerpts: tuple[ExcerptInput, ...]

    @classmethod
    def from_mapping(cls, document: dict[str, Any]) -> ExcerptIntake:
        """Human-reviewed intake file: one preserved source and its reviewed quotations."""
        return cls(
            ExcerptVersion(document["version"]),
            SourceDocument.from_mapping(document["source"]),
            tuple(
                ExcerptInput(
                    quote=item["quote"],
                    subject_place_id=int(item["subject_place_id"]),
                    aspect=ChunkAspect(item["aspect"]),
                    context=item["context"],
                    relations=tuple(item.get("relations", ())),
                    relation_certainty=RelationCertainty(item.get("relation_certainty", RelationCertainty.NOT_REVIEWED.value)),
                    reviewer=item.get("reviewer"),
                )
                for item in document["excerpts"]
            ),
        )

    def execute(self, config: ExcerptConfig = ExcerptConfig()) -> ExcerptResult:
        matches = [module for module in EXCERPT_MODULES if module.supports(self.version)]
        if len(matches) != 1:
            raise ValueError("Exactly one excerpt module must support the intake version")
        return matches[0].execute(self.source, list(self.excerpts), config)
