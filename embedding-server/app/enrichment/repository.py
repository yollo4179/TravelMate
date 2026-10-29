"""FastAPI-owned enrichment snapshots and reindex jobs; Spring place facts stay unchanged."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
import uuid

from .contracts import CollectionStatus, ExistingPlace
from .evidence import normalize_response, searchable_claims


async def ensure_schema(pool: Any) -> None:
    await pool.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
    from app.contextual.repository import ensure_schema as ensure_contextual_schema
    await ensure_contextual_schema(pool)


async def existing_places(pool: Any, identifiers: list[int] | None) -> list[ExistingPlace]:
    rows = await pool.fetch(
        "SELECT * FROM place_embeddings WHERE document_status = 'READY' AND source_version = latest_seen_version "
        "AND ($1::bigint[] IS NULL OR place_id = ANY($1::bigint[])) ORDER BY place_id",
        identifiers,
    )
    places = [ExistingPlace.from_mapping(dict(row)) for row in rows]
    if identifiers is not None and {place.place_id for place in places} != set(identifiers):
        raise ValueError("Some selected places are missing, deleted or awaiting source indexing")
    return places


async def apply_record(pool: Any, record_path: Path) -> str:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record["status"] != CollectionStatus.COLLECTED:
        raise ValueError("Only completed, validated collection records may be applied")
    place = ExistingPlace.from_mapping(record["place"])
    raw = json.loads(record_path.with_name("raw_response.json").read_text(encoding="utf-8"))
    normalized = normalize_response(place, raw)
    if normalized != record["document"] or place.source_fingerprint != record["source_fingerprint"]:
        raise ValueError("Enrichment artifact differs from its raw response or original source")
    if not searchable_claims(normalized):
        raise ValueError("No non-conflicting excerpt-supported claims are available for indexing")
    collected_at = datetime.fromisoformat(record["collected_at"])
    if collected_at.tzinfo is None:
        raise ValueError("Collection timestamp requires an explicit timezone")
    snapshot_id = uuid.UUID(record["snapshot_id"])
    async with pool.acquire() as connection:
        async with connection.transaction():
            row = await connection.fetchrow("SELECT * FROM place_embeddings WHERE place_id = $1 FOR UPDATE", place.place_id)
            if not row or row["document_status"] != "READY" or row["source_version"] != row["latest_seen_version"]:
                raise ValueError("The existing place is unavailable or its source is being updated")
            current = ExistingPlace.from_mapping(dict(row))
            if current.source_fingerprint != place.source_fingerprint:
                raise ValueError("Existing place changed after collection; collect again before applying")
            inserted = await connection.execute(
                """INSERT INTO place_enrichment_snapshots
                (snapshot_id, place_id, source_version, source_fingerprint, request_hash, record, raw_response, collected_at)
                VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8) ON CONFLICT (snapshot_id) DO NOTHING""",
                snapshot_id, place.place_id, row["source_version"], place.source_fingerprint,
                record["request_hash"], json.dumps(record, ensure_ascii=False, allow_nan=False),
                json.dumps(raw, ensure_ascii=False, allow_nan=False), collected_at,
            )
            if inserted == "INSERT 0 0":
                return "ALREADY_APPLIED"
            event_id = uuid.uuid4()
            payload = {"event_id": str(event_id), "event_type": "PLACE_UPSERTED", "place_id": place.place_id,
                       "source_version": row["source_version"], "source": place.to_dict()}
            await connection.execute(
                """INSERT INTO place_index_jobs (job_id, event_id, place_id, source_version, payload)
                VALUES ($1,$2,$3,$4,$5::jsonb)""",
                uuid.uuid4(), event_id, place.place_id, row["source_version"], json.dumps(payload, ensure_ascii=False, allow_nan=False),
            )
    return "REINDEX_QUEUED"


async def latest_snapshot(pool: Any, place: ExistingPlace) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """SELECT snapshot_id, record FROM place_enrichment_snapshots
        WHERE place_id = $1 AND source_fingerprint = $2
        ORDER BY collected_at DESC, snapshot_id DESC LIMIT 1""",
        place.place_id, place.source_fingerprint,
    )
    if row is None:
        return None
    record = json.loads(row["record"]) if isinstance(row["record"], str) else row["record"]
    return {"snapshot_id": row["snapshot_id"], "document": record["document"],
            "actual_model": record.get("actual_model"), "prompt_version": record.get("prompt_version")}
