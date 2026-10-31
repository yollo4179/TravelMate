from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
import json
import hashlib
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
from .profiles import resolve_execution_profile
from .validation import ExclusionReason, current_validation_version


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
    prepared_request: dict[str, Any] | None = None,
    request_profile_id: str | None = None,
) -> Path:
    canonical = request_payload(bundle.places, bundle.sources, settings, prompt_version=prompt_version)
    payload = deepcopy(prepared_request) if prepared_request is not None else canonical
    validate_request(payload, canonical, prompt_version, request_profile_id)
    validation_version = current_validation_version(prompt_version)
    request_hash = request_fingerprint(payload, prompt_version, request_profile_id, validation_version)
    directory = root / archive_directory(bundle.places[0]) / "requests" / request_hash
    pointer = directory / "latest.json"
    if http is not None and pointer.exists() and not refresh:
        previous = directory / json.loads(pointer.read_text(encoding="utf-8"))["record_path"]
        if not previous.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Cache path escapes archive")
        previous_record = json.loads(previous.read_text(encoding="utf-8"))
        if previous_record["status"] == CollectionStatus.COLLECTED and previous_record["request_hash"] == request_hash:
            load_record(previous)
            return previous
    run = directory / str(uuid.uuid4())
    write_json(run / "sources.json", bundle.to_dict())
    write_json(run / "request.json", payload)
    record = {"schema_version": 1, "request_hash": request_hash, "prompt_version": prompt_version,
              "created_at": datetime.now(UTC).isoformat(), "status": CollectionStatus.PLANNED.value,
              "validation_version": validation_version}
    if request_profile_id:
        record["request_profile_id"] = request_profile_id
    if http is not None:
        try:
            raw = await generate(http, settings, payload)
            write_json(run / "raw_response.json", raw)
            record.update(response_fields(raw, bundle, payload, prompt_version, request_profile_id, validation_version))
            record.update(status=CollectionStatus.COLLECTED.value, usage=raw.get("usage"))
        except Exception as exception:
            record.update(status=CollectionStatus.FAILED.value, error_type=type(exception).__name__)
            if isinstance(exception, httpx.HTTPStatusError):
                record["http_status"] = exception.response.status_code
    write_json(run / "record.json", record)
    if record["status"] == CollectionStatus.COLLECTED:
        publish_record(root, bundle, run, request_hash)
    return run / "record.json"


def publish_record(root: Path, bundle: SourceBundle, run: Path, request_hash: str) -> None:
    temporary = run.parent / f".latest-{run.name}.json"
    write_json(temporary, {"record_path": f"{run.name}/record.json"})
    temporary.replace(run.parent / "latest.json")
    for place in bundle.places[1:]:
        write_json(root / archive_directory(place) / "references" / f"{request_hash}-{run.name}.json",
                   {"record_path": str((run / "record.json").resolve()), "place_id": place.place_id})


def request_fingerprint(
    payload: dict[str, Any],
    prompt_version: str,
    profile_id: str | None = None,
    validation_version: str | None = None,
) -> str:
    identity = {"payload": payload, "prompt_version": prompt_version}
    if profile_id:
        identity["request_profile_id"] = profile_id
    if validation_version is not None:
        identity["validation_version"] = validation_version
    return fingerprint(identity)


def validate_request(
    payload: dict[str, Any],
    canonical: dict[str, Any],
    prompt_version: str,
    profile_id: str | None,
) -> None:
    if profile_id:
        resolve_execution_profile(profile_id).validate_request(payload, canonical, prompt_version)
        return
    if payload != canonical:
        raise ValueError("Contextual request or source archive changed")


def load_record(
    path: Path,
    *,
    baseline_profile: str | None = None,
) -> tuple[SourceBundle, list[SearchChunk], dict[str, Any]]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["status"] != CollectionStatus.COLLECTED:
        raise ValueError("Only completed contextual records may be applied")
    prompt_version = record["prompt_version"]
    recorded_profile = record.get("request_profile_id")
    if baseline_profile is not None:
        profile = resolve_execution_profile(baseline_profile)
        if recorded_profile is not None and recorded_profile != baseline_profile:
            raise ValueError("Baseline profile differs from recorded profile")
        if recorded_profile is None and prompt_version != profile.original_prompt_version:
            raise ValueError("Unregistered archives require the original local prompt version")
    bundle = SourceBundle.from_mapping(json.loads(path.with_name("sources.json").read_text(encoding="utf-8")))
    raw = json.loads(path.with_name("raw_response.json").read_text(encoding="utf-8"))
    payload = json.loads(path.with_name("request.json").read_text(encoding="utf-8"))
    selector = {"preset": payload["preset"]} if "preset" in payload else {"model": payload["model"]}
    expected = request_payload(bundle.places, bundle.sources, AgentSettings(**selector), prompt_version=prompt_version)
    validate_request(payload, expected, prompt_version, recorded_profile or baseline_profile)
    # Legacy request hashes remain unchanged; only new profiled records bind the profile ID.
    validation_version = record.get("validation_version")
    if request_fingerprint(payload, prompt_version, recorded_profile, validation_version) != record["request_hash"]:
        raise ValueError("Contextual request or source archive changed")
    if "actual_model" in record and record["actual_model"] != raw.get("model"):
        raise ValueError("Recorded model differs from preserved response")
    chunks = parse_chunks(
        raw,
        bundle.places,
        bundle.sources,
        prompt_version=prompt_version,
        response_schema=payload["response_format"]["json_schema"]["schema"],
        request_profile_id=recorded_profile,
        validation_version=validation_version,
    )
    if [chunk.to_dict() for chunk in chunks] != record["chunks"]:
        raise ValueError("Contextual record differs from preserved response")
    if validation_version is not None:
        expected_excluded = excluded_chunks(raw, bundle, chunks)
        if expected_excluded != record.get("excluded_chunks"):
            raise ValueError("Excluded chunks differ from preserved response")
    return bundle, chunks, record


def excluded_chunks(raw: dict[str, Any], bundle: SourceBundle, chunks: list[SearchChunk]) -> list[dict[str, Any]]:
    text = "".join(part["text"] for item in raw.get("output", []) if item.get("type") == "message"
                   for part in item.get("content", []) if part.get("type") == "output_text")
    retained = {(chunk.source.source_id, chunk.start, chunk.end) for chunk in chunks}
    sources = {source.source_id: source for source in bundle.sources}
    return [{**chunk, "chunk_text": sources[chunk["source_id"]].text[chunk["start"]:chunk["end"]],
             "exclusion_reason": ExclusionReason.NO_SUBJECT if chunk["place_refs"] else ExclusionReason.UNATTRIBUTED}
            for chunk in json.loads(text)["chunks"]
            if (chunk["source_id"], chunk["start"], chunk["end"]) not in retained]


def response_fields(
    raw: dict[str, Any],
    bundle: SourceBundle,
    payload: dict[str, Any],
    prompt_version: str,
    request_profile_id: str | None,
    validation_version: str,
) -> dict[str, Any]:
    chunks = parse_chunks(
        raw,
        bundle.places,
        bundle.sources,
        prompt_version=prompt_version,
        response_schema=payload["response_format"]["json_schema"]["schema"],
        request_profile_id=request_profile_id,
        validation_version=validation_version,
    )
    return {"chunks": [chunk.to_dict() for chunk in chunks], "actual_model": raw.get("model"),
            "excluded_chunks": excluded_chunks(raw, bundle, chunks)}


def revalidate_record(path: Path, root: Path, *, baseline_profile: str | None = None) -> Path:
    """API 호출 없이 새 검증 결과를 별도 아카이브에 보존한다."""
    originals = {name: path.with_name(name).read_bytes()
                 for name in ("record.json", "request.json", "sources.json", "raw_response.json")}
    original = json.loads(originals["record.json"])
    if original["status"] == CollectionStatus.COLLECTED:
        load_record(path, baseline_profile=baseline_profile)
    elif original["status"] != CollectionStatus.FAILED or original.get("error_type") != "ValueError":
        raise ValueError("Revalidation requires a collected response or a preserved validation failure")
    prompt_version = original["prompt_version"]
    profile_id = original.get("request_profile_id")
    if baseline_profile is not None:
        profile = resolve_execution_profile(baseline_profile)
        if profile_id not in (None, baseline_profile):
            raise ValueError("Baseline profile differs from recorded profile")
        if profile_id is None and prompt_version != profile.original_prompt_version:
            raise ValueError("Unregistered archives require the original local prompt version")
    payload = json.loads(originals["request.json"])
    bundle = SourceBundle.from_mapping(json.loads(originals["sources.json"]))
    selector = {key: payload[key] for key in ("model", "preset") if key in payload}
    canonical = request_payload(bundle.places, bundle.sources, AgentSettings(**selector), prompt_version=prompt_version)
    validate_request(payload, canonical, prompt_version, profile_id or baseline_profile)
    if request_fingerprint(payload, prompt_version, profile_id, original.get("validation_version")) != original["request_hash"]:
        raise ValueError("Contextual request or source archive changed")
    raw = json.loads(originals["raw_response.json"])
    if "actual_model" in original and original["actual_model"] != raw.get("model"):
        raise ValueError("Recorded model differs from preserved response")
    profile_id = profile_id or baseline_profile
    validation_version = current_validation_version(prompt_version)
    fields = response_fields(raw, bundle, payload, prompt_version, profile_id, validation_version)
    request_hash = request_fingerprint(payload, prompt_version, profile_id, validation_version)
    run = root / archive_directory(bundle.places[0]) / "requests" / request_hash / str(uuid.uuid4())
    record = {"schema_version": 1, "request_hash": request_hash, "prompt_version": prompt_version,
              "validation_version": validation_version, "created_at": datetime.now(UTC).isoformat(),
              "status": CollectionStatus.COLLECTED.value, "api_calls": 0,
              "revalidated_from": {"record_path": str(path.resolve()),
                                   "file_sha256": {name: hashlib.sha256(content).hexdigest()
                                                   for name, content in originals.items()}}, **fields}
    if profile_id:
        record["request_profile_id"] = profile_id
    run.mkdir(parents=True)
    for name, content in originals.items():
        if name != "record.json":
            with (run / name).open("xb") as stream:
                stream.write(content)
    write_json(run / "record.json", record)
    load_record(run / "record.json")
    publish_record(root, bundle, run, request_hash)
    return run / "record.json"


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
