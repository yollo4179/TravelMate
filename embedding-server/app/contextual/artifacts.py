from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
import os
from typing import Any
import uuid

import httpx

from app.enrichment.agent import AgentSettings
from app.enrichment.artifacts import write_json
from app.enrichment.contracts import CollectionStatus, ExistingPlace, fingerprint
from .agent import PROMPT_VERSION, generate, parse_chunks, request_payload
from .contracts import SearchChunk, SourceDocument, archive_directory
from .pipeline import normalize_source
from .pipeline import tourapi_chunks


@dataclass(frozen=True)
class SourceBundle:
    places: list[ExistingPlace]
    sources: list[SourceDocument]

    @classmethod
    def from_mapping(cls, document: dict[str, Any]) -> SourceBundle:
        places = [ExistingPlace.from_mapping(place) for place in document["places"]]
        sources = [normalize_source(source) for source in document["sources"]]
        if not places or len({place.place_id for place in places}) != len(places):
            raise ValueError("Bundle places must be nonempty and unique")
        if not sources or len({source.source_id for source in sources}) != len(sources):
            raise ValueError("Bundle sources must be nonempty and unique")
        return cls(places, sources)

    def to_dict(self) -> dict[str, Any]:
        return {"places": [place.to_dict() for place in self.places], "sources": [source.to_dict() for source in self.sources]}

    @classmethod
    def from_enrichment_record(cls, path: Path) -> SourceBundle:
        from app.enrichment.evidence import normalize_response
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["status"] != CollectionStatus.COLLECTED:
            raise ValueError("A completed enrichment record is required")
        place = ExistingPlace.from_mapping(record["place"])
        if record["source_fingerprint"] != place.source_fingerprint:
            raise ValueError("Enrichment source identity changed")
        raw = json.loads(path.with_name("raw_response.json").read_text(encoding="utf-8"))
        document = normalize_response(place, raw)
        if document != record["document"]:
            raise ValueError("Enrichment record differs from its preserved response")
        official = tourapi_chunks(place)
        sources = {chunk.source.source_id: chunk.source for chunk in official}
        by_url: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for source in document["sources"]:
            if source["snippet"].strip():
                by_url[source["url"]].append(source)
        for excerpts in by_url.values():
            source = max(excerpts, key=lambda item: len(item["snippet"]))
            normalized = normalize_source({"source_type": "web_excerpt", "title": source.get("title") or place.name,
                "text": source["snippet"], "metadata": {"source_url": source["url"], "capture_scope": "excerpt",
                    "published_at": source.get("published_at"), "provider_excerpts": excerpts,
                    "excerpt_selection": "longest-provider-excerpt-v1"}})
            sources[normalized.source_id] = normalized
        return cls.from_mapping({"places": [place.to_dict()], "sources": [source.to_dict() for source in sources.values()]})


async def collect_bundle(
    bundle: SourceBundle,
    settings: AgentSettings,
    root: Path,
    http: httpx.AsyncClient | None,
    *,
    refresh: bool = False,
    prompt_version: str = PROMPT_VERSION,
) -> Path:
    payload = request_payload(bundle.places, bundle.sources, settings, prompt_version=prompt_version)
    request_hash = fingerprint({"payload": payload, "prompt_version": prompt_version})
    directory = root / archive_directory(bundle.places[0]) / "requests" / request_hash
    pointer = directory / "latest.json"
    if http is not None and pointer.exists() and not refresh:
        previous = directory / json.loads(pointer.read_text())["record_path"]
        if not previous.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Cache path escapes archive")
        previous_record = json.loads(previous.read_text())
        if previous_record["status"] == CollectionStatus.COLLECTED and previous_record["request_hash"] == request_hash:
            load_record(previous)
            return previous
    run = directory / str(uuid.uuid4())
    write_json(run / "sources.json", bundle.to_dict())
    write_json(run / "request.json", payload)
    record = {"schema_version": 1, "request_hash": request_hash, "prompt_version": prompt_version,
              "created_at": datetime.now(UTC).isoformat(), "status": CollectionStatus.PLANNED.value}
    if http is not None:
        try:
            raw = await generate(http, settings, payload)
            write_json(run / "raw_response.json", raw)
            chunks = parse_chunks(raw, bundle.places, bundle.sources, prompt_version=prompt_version)
            record.update(status=CollectionStatus.COLLECTED.value, chunks=[chunk.to_dict() for chunk in chunks],
                          actual_model=raw.get("model"), usage=raw.get("usage"))
        except Exception as exception:
            record.update(status=CollectionStatus.FAILED.value, error_type=type(exception).__name__)
            if isinstance(exception, httpx.HTTPStatusError):
                record["http_status"] = exception.response.status_code
    write_json(run / "record.json", record)
    if record["status"] == CollectionStatus.COLLECTED:
        temporary = directory / f".latest-{run.name}.json"
        write_json(temporary, {"record_path": f"{run.name}/record.json"})
        temporary.replace(pointer)
        for place in bundle.places[1:]:
            write_json(root / archive_directory(place) / "references" / f"{request_hash}-{run.name}.json",
                       {"record_path": str((run / "record.json").resolve()), "place_id": place.place_id})
    return run / "record.json"


def load_record(path: Path) -> tuple[SourceBundle, list[SearchChunk], dict[str, Any]]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["status"] != CollectionStatus.COLLECTED:
        raise ValueError("Only completed contextual records may be applied")
    prompt_version = record["prompt_version"]
    bundle = SourceBundle.from_mapping(json.loads(path.with_name("sources.json").read_text(encoding="utf-8")))
    raw = json.loads(path.with_name("raw_response.json").read_text(encoding="utf-8"))
    chunks = parse_chunks(raw, bundle.places, bundle.sources, prompt_version=prompt_version)
    payload = json.loads(path.with_name("request.json").read_text(encoding="utf-8"))
    selector = {"preset": payload["preset"]} if "preset" in payload else {"model": payload["model"]}
    expected = request_payload(bundle.places, bundle.sources, AgentSettings(**selector), prompt_version=prompt_version)
    if payload != expected or fingerprint({"payload": payload, "prompt_version": prompt_version}) != record["request_hash"]:
        raise ValueError("Contextual request or source archive changed")
    if [chunk.to_dict() for chunk in chunks] != record["chunks"]:
        raise ValueError("Contextual record differs from preserved response")
    return bundle, chunks, record


def archive_index_input(root: Path, place: ExistingPlace, chunks: list[SearchChunk]) -> None:
    document = {"place": place.to_dict(), "sources": list({chunk.source.source_id: chunk.source.to_dict() for chunk in chunks}.values()),
                "chunks": [chunk.to_dict() for chunk in chunks]}
    directory = root / archive_directory(place) / "index-inputs"
    destination = directory / f"{fingerprint(document)}.json"
    if destination.exists():
        if json.loads(destination.read_text(encoding="utf-8")) != document:
            raise ValueError("Existing index archive content changed")
        return
    temporary = directory / f".pending-{uuid.uuid4()}.json"
    write_json(temporary, document)
    try:
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if json.loads(destination.read_text(encoding="utf-8")) != document:
                raise ValueError("Concurrent index archive differs")
    finally:
        temporary.unlink()
