from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import re
from typing import Any
import uuid

from app.enrichment.contracts import ExistingPlace, fingerprint
from app.enrichment.evidence import source_url

from .relations import ActiveChunkRole, independent_relations, endpoint_ids, validate_independent_relations

MAX_ACTIVE_CHUNKS = 20


class SplitterVersion(StrEnum):
    LEGACY = "source-span-v1"
    SENTENCE = "sentence-paragraph-v2"


SPLITTER_VERSION = SplitterVersion.LEGACY.value
NAMESPACE = uuid.UUID("ec22a193-8827-4ab2-8906-c5a989dfd88f")


class SourceType(StrEnum):
    TOURAPI = "tourapi"
    BLOG = "blog_post"
    REVIEW = "review"
    WEB = "web_excerpt"


class PlaceRole(StrEnum):
    SUBJECT = "subject"
    VIEW_TARGET = "view_target"
    MENTIONED = "mentioned"


class ContentKind(StrEnum):
    LANDSCAPE = "landscape"
    FACILITY = "facility"
    MOVEMENT = "movement"
    OTHER = "other"


class MovementCondition(StrEnum):
    STAIRS = "stairs"
    DISTANCE = "distance"
    DURATION = "duration"
    OTHER = "other"


class CaptureScope(StrEnum):
    FULL = "full_text"
    EXCERPT = "excerpt"
    FIELD = "field"


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    source_type: SourceType
    title: str
    text: str
    metadata: dict[str, Any]

    @property
    def source_version(self) -> str:
        return fingerprint({"title": self.title, "text": self.text})

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "source_version": self.source_version}

    @classmethod
    def from_mapping(cls, source: dict[str, Any]) -> SourceDocument:
        kind = SourceType(source["source_type"])
        metadata = dict(source["metadata"])
        CaptureScope(metadata["capture_scope"])
        identity = metadata.get("source_url") or metadata.get("tour_content_id")
        if metadata.get("source_url"):
            source_url(metadata["source_url"])
        if not identity or not isinstance(source["text"], str) or not source["text"].strip() or not isinstance(source["title"], str):
            raise ValueError("Sources require an identity and preserved nonempty text")
        identifier = str(uuid.uuid5(NAMESPACE, f"{kind}:{identity}:{metadata.get('field', '')}"))
        result = cls(identifier, kind, source["title"], source["text"], metadata)
        if source.get("source_id", identifier) != identifier:
            raise ValueError("Source identity does not match its provenance")
        if source.get("source_version", result.source_version) != result.source_version:
            raise ValueError("Source version does not match preserved content")
        return result


@dataclass(frozen=True)
class SearchChunk:
    source: SourceDocument
    start: int
    end: int
    context_text: str
    place_refs: list[dict[str, Any]]
    generation: dict[str, Any]
    entities: list[dict[str, Any]] = field(default_factory=list)
    hypothetical_questions: list[str] = field(default_factory=list)
    splitter_version: str = SPLITTER_VERSION
    content_kind: str | None = None
    relations: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        SplitterVersion(self.splitter_version)
        if self.content_kind is not None:
            ContentKind(self.content_kind)
        independent = independent_relations(self.relations)
        if independent:
            validate_independent_relations(self.relations, self.place_refs, self.source.text, self.start, self.end)
            for relation in self.relations:
                for condition in relation["conditions"]:
                    MovementCondition(condition["kind"])
        if self.relations and not independent and self.content_kind != ContentKind.MOVEMENT:
            raise ValueError("이동 관계는 이동 내용의 청크에만 둘 수 있습니다")
        if self.content_kind == ContentKind.MOVEMENT:
            if not self.relations:
                raise ValueError("이동 청크에는 출발지·도착지 관계가 필요합니다")
            endpoint_ids = {endpoint["place_id"] for relation in self.relations
                            for endpoint in (relation["origin"], relation["destination"]) if endpoint["place_id"] is not None}
            subject_ids = {ref["place_id"] for ref in self.place_refs if ref["role"] == PlaceRole.SUBJECT}
            if not independent and endpoint_ids != subject_ids:
                raise ValueError("이동의 알려진 출발지·도착지가 핵심 장소여야 합니다")
            for relation in self.relations:
                for condition in relation["conditions"]:
                    MovementCondition(condition["kind"])
                    if not condition["quote"] or condition["quote"] not in self.chunk_text:
                        raise ValueError("이동 조건은 현재 원문의 정확한 인용이어야 합니다")
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end <= len(self.source.text):
            raise ValueError("Chunk span must address the preserved source version")
        if not self.context_text.strip() or len(self.context_text) > 600:
            raise ValueError("Chunk context must contain 1..600 characters")
        if not self.place_refs or len({ref["place_id"] for ref in self.place_refs}) != len(self.place_refs):
            raise ValueError("Chunk place references must be present and unique")
        for reference in self.place_refs:
            PlaceRole(reference["role"])
            if type(reference["place_id"]) is not int or reference["place_id"] <= 0:
                raise ValueError("Invalid referenced place ID")
        if not self.subject_place_ids and not self.relation_place_ids:
            raise ValueError("Chunks require at least one subject place")

    @property
    def subject_place_ids(self) -> set[int]:
        return {ref["place_id"] for ref in self.place_refs if ref["role"] == PlaceRole.SUBJECT}

    @property
    def relation_place_ids(self) -> set[int]:
        return endpoint_ids(self.relations) if independent_relations(self.relations) else set()

    @property
    def index_place_ids(self) -> set[int]:
        return self.subject_place_ids | self.relation_place_ids

    def active_role(self, place_id: int) -> ActiveChunkRole | None:
        if place_id in self.subject_place_ids:
            return ActiveChunkRole.SUBJECT
        return ActiveChunkRole.RELATION_ENDPOINT if place_id in self.relation_place_ids else None

    @property
    def chunk_id(self) -> str:
        return str(uuid.uuid5(NAMESPACE, f"{self.source.source_id}:{self.source.source_version}:{self.start}:{self.end}:{self.splitter_version}"))

    @property
    def chunk_text(self) -> str:
        return self.source.text[self.start:self.end]

    @property
    def embedding_text(self) -> str:
        return f"{self.context_text}\n\n{self.chunk_text}"

    @property
    def context_version(self) -> str:
        return fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id, "source_id": self.source.source_id,
            "source_version": self.source.source_version, "source_type": self.source.source_type,
            "title": self.source.title, "chunk_text": self.chunk_text,
            "source_span": {"start": self.start, "end": self.end, "unit": "unicode_codepoint"},
            "splitter_version": self.splitter_version, "context_text": self.context_text,
            "place_refs": self.place_refs, "entities": self.entities,
            "hypothetical_questions": self.hypothetical_questions,
            "generation": self.generation,
            **({"content_kind": self.content_kind, "relations": self.relations} if self.content_kind is not None else {}),
        }

    @classmethod
    def from_mapping(cls, source: SourceDocument, chunk: dict[str, Any]) -> SearchChunk:
        span = chunk["source_span"]
        result = cls(source, span["start"], span["end"], chunk["context_text"], chunk["place_refs"],
                     chunk["generation"], chunk.get("entities", []), chunk.get("hypothetical_questions", []),
                     chunk.get("splitter_version", SPLITTER_VERSION), chunk.get("content_kind"), chunk.get("relations", []))
        if chunk.get("chunk_id", result.chunk_id) != result.chunk_id or chunk.get("chunk_text", result.chunk_text) != result.chunk_text:
            raise ValueError("Chunk ID or quotation differs from its source span")
        return result


def archive_directory(place: ExistingPlace) -> str:
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", place.name).strip(". ")[:100] or "place"
    return f"{place.place_id}_{name}"
