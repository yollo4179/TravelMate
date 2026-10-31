from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
import uuid

from app.enrichment.contracts import ExistingPlace, fingerprint
from .artifacts import load_record
from .contracts import PlaceRole, SearchChunk, SourceDocument, SPLITTER_VERSION


async def ensure_schema(pool: Any) -> None:
    await pool.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))


async def preserve_chunks(connection: Any, chunks: list[SearchChunk]) -> None:
    for chunk in sorted(chunks, key=lambda item: (item.source.source_id, item.chunk_id, item.context_version)):
        await connection.execute(
            """INSERT INTO retrieval_source_versions(source_id,source_version,document) VALUES($1,$2,$3::jsonb)
            ON CONFLICT DO NOTHING""", uuid.UUID(chunk.source.source_id), chunk.source.source_version,
            json.dumps(chunk.source.to_dict(), ensure_ascii=False))
        await connection.execute(
            """INSERT INTO retrieval_chunks(chunk_id,source_id,source_version,start_offset,end_offset,chunk_text,splitter_version)
            VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING""", uuid.UUID(chunk.chunk_id),
            uuid.UUID(chunk.source.source_id), chunk.source.source_version, chunk.start, chunk.end, chunk.chunk_text, SPLITTER_VERSION)
        await connection.execute(
            """INSERT INTO retrieval_chunk_contexts(chunk_id,context_version,document) VALUES($1,$2,$3::jsonb)
            ON CONFLICT DO NOTHING""", uuid.UUID(chunk.chunk_id), chunk.context_version,
            json.dumps(chunk.to_dict(), ensure_ascii=False))


async def apply_bundle(pool: Any, path: Path) -> str:
    bundle, chunks, record = load_record(path)
    if not chunks:
        return "NO_INDEXABLE_CHUNKS"
    subject_places = {ref["place_id"] for chunk in chunks for ref in chunk.place_refs if ref["role"] == PlaceRole.SUBJECT}
    manifest = {"sources": [source.to_dict() for source in bundle.sources], "chunks": [chunk.to_dict() for chunk in chunks]}
    async with pool.acquire() as connection:
        async with connection.transaction():
            # Stable lock order makes multi-place application atomic without deadlocks.
            for place in sorted(bundle.places, key=lambda item: item.place_id):
                row = await connection.fetchrow("SELECT * FROM place_embeddings WHERE place_id=$1 FOR UPDATE", place.place_id)
                if not row or row["document_status"] != "READY" or row["source_version"] != row["latest_seen_version"]:
                    raise ValueError("Place is unavailable or awaiting source indexing")
                if ExistingPlace.from_mapping(dict(row)).source_fingerprint != place.source_fingerprint:
                    raise ValueError("Place changed after contextual generation")
            await preserve_chunks(connection, chunks)
            for source in bundle.sources:
                await connection.execute(
                    """INSERT INTO retrieval_source_versions(source_id,source_version,document)
                    VALUES($1,$2,$3::jsonb) ON CONFLICT DO NOTHING""",
                    uuid.UUID(source.source_id), source.source_version, json.dumps(source.to_dict(), ensure_ascii=False))
            changed = False
            for place in bundle.places:
                if place.place_id not in subject_places:
                    continue
                identifier = fingerprint({"request_hash": record["request_hash"], "place": place.to_dict(), "manifest": manifest})
                inserted = await connection.execute(
                    """INSERT INTO retrieval_chunk_bundles(bundle_id,place_id,place_fingerprint,manifest)
                    VALUES($1,$2,$3,$4::jsonb) ON CONFLICT DO NOTHING""", identifier, place.place_id,
                    place.source_fingerprint, json.dumps(manifest, ensure_ascii=False))
                if inserted == "INSERT 0 0":
                    continue
                changed = True
                await connection.execute("UPDATE place_embeddings SET chunk_generation=chunk_generation+1 WHERE place_id=$1", place.place_id)
                event_id = uuid.uuid4()
                payload = {"event_id": str(event_id), "event_type": "PLACE_UPSERTED", "place_id": place.place_id,
                           "source": place.to_dict()}
                payload["source_version"] = await connection.fetchval("SELECT source_version FROM place_embeddings WHERE place_id=$1", place.place_id)
                await connection.execute(
                    """INSERT INTO place_index_jobs(job_id,event_id,place_id,source_version,payload)
                    VALUES($1,$2,$3,$4,$5::jsonb)""", uuid.uuid4(), event_id, place.place_id,
                    payload["source_version"], json.dumps(payload, ensure_ascii=False))
    return "REINDEX_QUEUED" if changed else "ALREADY_APPLIED"


async def desired_chunks(pool: Any, place: ExistingPlace) -> tuple[int, list[SearchChunk]]:
    row = await pool.fetchrow(
        """SELECT p.chunk_generation, b.manifest FROM place_embeddings p LEFT JOIN LATERAL
        (SELECT manifest FROM retrieval_chunk_bundles WHERE place_id=p.place_id AND place_fingerprint=$2
         ORDER BY applied_order DESC LIMIT 1) b ON true WHERE p.place_id=$1""",
        place.place_id, place.source_fingerprint)
    if row is None:
        raise ValueError("Missing place for chunk indexing")
    if row["manifest"] is None:
        return row["chunk_generation"], []
    manifest = json.loads(row["manifest"]) if isinstance(row["manifest"], str) else row["manifest"]
    sources = {source["source_id"]: SourceDocument.from_mapping(source) for source in manifest["sources"]}
    return row["chunk_generation"], [SearchChunk.from_mapping(sources[chunk["source_id"]], chunk) for chunk in manifest["chunks"]]


async def activate_chunks(connection: Any, place_id: int, chunks: list[SearchChunk], vectors: list[list[float]]) -> None:
    if len(chunks) != len(vectors):
        raise ValueError("Embedding count differs from chunk count")
    for vector in vectors:
        if len(vector) != 1024 or not all(math.isfinite(value) for value in vector):
            raise ValueError("Contextual embeddings must be 1024 finite values")
    await preserve_chunks(connection, chunks)
    await connection.execute("DELETE FROM place_active_chunks WHERE place_id=$1", place_id)
    for slot, (chunk, vector) in enumerate(zip(chunks, vectors), 1):
        await connection.execute(
            "UPDATE retrieval_chunk_contexts SET embedding=$3::vector WHERE chunk_id=$1 AND context_version=$2",
            uuid.UUID(chunk.chunk_id), chunk.context_version, "[" + ",".join(map(str, vector)) + "]")
        await connection.execute(
            "INSERT INTO place_active_chunks(place_id,slot,chunk_id,context_version) VALUES($1,$2,$3,$4)",
            place_id, slot, uuid.UUID(chunk.chunk_id), chunk.context_version)
