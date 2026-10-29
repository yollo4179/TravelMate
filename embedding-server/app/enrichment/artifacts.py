"""Immutable request/response archives and a cache keyed by the exact source and prompt."""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import uuid

import httpx

from .agent import AgentClient, AgentSettings, PROMPT_VERSION, request_payload
from .contracts import CollectionStatus, ExistingPlace, fingerprint
from .evidence import normalize_response, searchable_claims
from app.contextual.contracts import archive_directory


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


async def collect_place(
    place: ExistingPlace,
    settings: AgentSettings,
    output_root: Path,
    client: AgentClient | None,
    *,
    refresh: bool = False,
) -> Path:
    payload = request_payload(place, settings)
    request_hash = fingerprint({"source": place.to_dict(), "prompt_version": PROMPT_VERSION, "payload": payload})
    cache = output_root / "LocationReview" / archive_directory(place) / "requests" / request_hash
    pointer = cache / "latest.json"
    if client is not None and not refresh and pointer.exists():
        previous = cache / json.loads(pointer.read_text(encoding="utf-8"))["record_path"]
        if not previous.resolve().is_relative_to(cache.resolve()):
            raise ValueError("Cached record path escapes its request archive")
        record = json.loads(previous.read_text(encoding="utf-8"))
        if record["status"] == CollectionStatus.COLLECTED and record["request_hash"] == request_hash:
            return previous
    snapshot_id = str(uuid.uuid4())
    run = cache / snapshot_id
    write_json(run / "request.json", payload)
    record = {
        "schema_version": 1, "snapshot_id": snapshot_id, "place": place.to_dict(),
        "source_fingerprint": place.source_fingerprint, "request_hash": request_hash,
        "prompt_version": PROMPT_VERSION, "collected_at": datetime.now(UTC).isoformat(),
        "status": CollectionStatus.PLANNED.value,
    }
    if client is None:
        write_json(run / "record.json", record)
        return run / "record.json"
    try:
        raw = await client.collect(place)
        write_json(run / "raw_response.json", raw)
        document = normalize_response(place, raw)
        record.update(status=CollectionStatus.COLLECTED.value, response_id=raw.get("id"),
                      actual_model=raw.get("model"), usage=raw.get("usage"),
                      document=document, searchable_claim_count=len(searchable_claims(document)))
    except Exception as exception:
        record.update(status=CollectionStatus.FAILED.value, error_type=type(exception).__name__)
        if isinstance(exception, httpx.HTTPStatusError):
            record["http_status"] = exception.response.status_code
    write_json(run / "record.json", record)
    if record["status"] == CollectionStatus.COLLECTED:
        cache.mkdir(parents=True, exist_ok=True)
        temporary = cache / f".latest-{snapshot_id}.json"
        write_json(temporary, {"record_path": f"{snapshot_id}/record.json"})
        temporary.replace(pointer)
    return run / "record.json"
