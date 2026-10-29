from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import re
from typing import Any
import uuid

from app.enrichment.contracts import ExistingPlace, fingerprint
from app.enrichment.evidence import source_url

MAX_ACTIVE_CHUNKS = 20
SPLITTER_VERSION = "source-span-v1"
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

    def __post_init__(self) -> None:
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
        if not any(ref["role"] == PlaceRole.SUBJECT for ref in self.place_refs):
            raise ValueError("Chunks require at least one subject place")

    @property
    def chunk_id(self) -> str:
        return str(uuid.uuid5(NAMESPACE, f"{self.source.source_id}:{self.source.source_version}:{self.start}:{self.end}:{SPLITTER_VERSION}"))

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
            "splitter_version": SPLITTER_VERSION, "context_text": self.context_text,
            "place_refs": self.place_refs, "entities": self.entities,
            "hypothetical_questions": self.hypothetical_questions,
            "generation": self.generation,
        }

    @classmethod
    def from_mapping(cls, source: SourceDocument, chunk: dict[str, Any]) -> SearchChunk:
        span = chunk["source_span"]
        result = cls(source, span["start"], span["end"], chunk["context_text"], chunk["place_refs"],
                     chunk["generation"], chunk.get("entities", []), chunk.get("hypothetical_questions", []))
        if chunk.get("chunk_id", result.chunk_id) != result.chunk_id or chunk.get("chunk_text", result.chunk_text) != result.chunk_text:
            raise ValueError("Chunk ID or quotation differs from its source span")
        return result


def archive_directory(place: ExistingPlace) -> str:
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", place.name).strip(". ")[:100] or "place"
    return f"{place.place_id}_{name}"
