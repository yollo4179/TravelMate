"""Prepare isolated B-plan resources without invoking inference or retrieval."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "embedding-server"))
from app.contextual.artifacts import load_record
from app.contextual.pipeline import select_active
from app.contextual.relation_vectors import relation_embedding_inputs
from app.contextual.review import reviewed_chunks
from app.enrichment.contracts import ExistingPlace, fingerprint

TOPICS = (
    "travelmate.b-eval.place-changes.v1",
    "travelmate.b-eval.recommendation-requests.v1",
    "travelmate.b-eval.recommendation-results.v1",
)
EVALUATION_USER = "b0000000-0000-4000-8000-000000000001"


class Stage(StrEnum):
    CONFIGURE = "configure"
    SNAPSHOT = "snapshot"
    LOAD = "load"
    VERIFY = "verify"


class EvidenceStatus(StrEnum):
    MISSING = "NO_PRESERVED_STRUCTURED_EVIDENCE"
    READY = "PRESERVED_STRUCTURED_EVIDENCE_READY"
    FIELD_READY = "PRESERVED_ORIGINAL_FIELD_READY"


@dataclass(frozen=True)
class DatabaseTarget:
    container: str
    user: str
    database: str


SOURCE_SPRING = DatabaseTarget("travel-postgres", "ssafy", "travel_db")
SOURCE_SEARCH = DatabaseTarget("travelmate-search-postgres", "travel_search", "travel_search_db")
TARGET_SPRING = DatabaseTarget("tm-b-eval-springdb", "b_eval", "travelmate_b_spring")
TARGET_SEARCH = DatabaseTarget("tm-b-eval-searchdb", "b_eval", "travelmate_b_search")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


async def command(*arguments: str, stdin: str | None = None) -> str:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(None if stdin is None else stdin.encode("utf-8")),
            timeout=60,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(f"Command failed: {arguments[:3]}: {stderr.decode('utf-8', errors='replace')[-1500:]}")
    return stdout.decode("utf-8").strip()


async def sql(target: DatabaseTarget, statement: str, *, write: bool = False) -> str:
    if write and target not in (TARGET_SPRING, TARGET_SEARCH):
        raise ValueError("Writes are restricted to the two named evaluation databases")
    transaction = "BEGIN" if write else "BEGIN READ ONLY"
    return await command(
        "docker", "exec", "-i", target.container,
        "psql", "-X", "-q", "-A", "-t", "-U", target.user, "-d", target.database,
        "-v", "ON_ERROR_STOP=1",
        stdin=f"{transaction};\nSET LOCAL standard_conforming_strings=on;\nSET LOCAL TIME ZONE 'Asia/Seoul';\n{statement}\nCOMMIT;\n",
    )


async def rows(target: DatabaseTarget, table: str, order: str) -> list[dict[str, Any]]:
    allowed = {"places", "place_embeddings", "place_active_chunks", "retrieval_source_versions", "place_original_field_evidence",
               "retrieval_chunks", "retrieval_chunk_contexts", "retrieval_relation_embeddings"}
    if table not in allowed or order not in ("id", "place_id", "chunk_id", "source_id"):
        raise ValueError("Unsupported snapshot table/order")
    output = await sql(target, f"SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY {order}), '[]'::jsonb) FROM {table} p;")
    return json.loads(output)


def insert_records(table: str, records: list[dict[str, Any]], *, identity: bool = False) -> str:
    allowed = {"places", "place_embeddings", "retrieval_source_versions", "retrieval_chunks", "place_original_field_evidence",
               "retrieval_chunk_contexts", "place_active_chunks", "retrieval_relation_embeddings"}
    if table not in allowed:
        raise ValueError("Unsupported import table")
    if not records:
        return ""
    literal = json.dumps(records, ensure_ascii=False, allow_nan=False).replace("'", "''")
    override = " OVERRIDING SYSTEM VALUE" if identity else ""
    return f"INSERT INTO {table}{override} SELECT * FROM jsonb_populate_recordset(NULL::{table}, '{literal}'::jsonb);"


def configure(runtime: Path, profile: Path) -> None:
    if runtime.exists():
        raise ValueError("Use a new runtime directory; existing credentials/artifacts are never overwritten")
    profile = profile.resolve(strict=True)
    verified_profile = read_json(profile)
    for key in ("model_path", "manifest_path", "library_directory", "renderer_path"):
        Path(verified_profile[key]).resolve(strict=True)
    runtime.mkdir(parents=True)
    (runtime / "observations").mkdir()
    (runtime / "traces").mkdir()
    credentials = {"db_password": secrets.token_hex(24), "jwt_secret": secrets.token_hex(48)}
    write_json(runtime / "private.json", credentials)
    env = {"B_EVAL_DB_PASSWORD": credentials["db_password"],
           "B_EVAL_REPOSITORY": ROOT.as_posix(), "B_EVAL_RUNTIME": runtime.as_posix()}
    (runtime / "runtime.env").write_text("".join(f"{key}={value}\n" for key, value in env.items()), encoding="utf-8")
    counter = ["C:/ssafy/Travelmate/embedding-server/.venv/Scripts/python.exe", "-X", "utf8",
               (ROOT / "Server/token_budget/exact_qwen_counter.py").as_posix(), "--profile", profile.as_posix()]
    settings = {
        "server.address": "127.0.0.1", "server.port": "18080",
        "spring.datasource.url": "jdbc:postgresql://127.0.0.1:55432/travelmate_b_spring",
        "spring.datasource.username": "b_eval", "spring.datasource.password": credentials["db_password"],
        "spring.jpa.hibernate.ddl-auto": "none", "spring.jpa.show-sql": "false",
        "spring.data.redis.host": "127.0.0.1", "spring.data.redis.port": "16379",
        "spring.data.redis.password": "", "spring.data.redis.ssl.enabled": "false",
        "spring.kafka.bootstrap-servers": "127.0.0.1:39092",
        "travelmate.kafka.place-changes-topic": TOPICS[0],
        "travelmate.kafka.recommendation-requests-topic": TOPICS[1],
        "travelmate.kafka.recommendation-results-topic": TOPICS[2],
        "embedding.server.url": "http://127.0.0.1:18000",
        "llm.provider": "QWEN", "ollama.base-url": "http://127.0.0.1:11434", "ollama.model": "qwen3:8b",
        "ollama.context-tokens": "8192", "ollama.max-output-tokens": "1536",
        "ollama.exact-counter-command": json.dumps(counter),
        "travelmate.conversation.allowed-tools": "SEARCH_PLACES",
        "travelmate.conversation.max-model-turns": "2", "travelmate.conversation.max-tool-calls": "1",
        "travelmate.conversation.tool-failure-policy": "STOP",
        "travelmate.observation.directory": (runtime / "observations").as_posix(),
        "travelmate.observation.mode": "LIVE", "jwt.secret": credentials["jwt_secret"],
        "logging.level.com.yollo": "INFO", "logging.level.com.yollo.TravelMate.jwt.JwtTokenProvider": "OFF",
        "logging.level.com.yollo.TravelMate.config.FilterChannelInterceptor": "OFF",
        "openai.api-key": "", "openai.model": "", "openai.base-url": "http://127.0.0.1:9",
        "LANGSMITH_API_KEY": "local-b-eval-no-external-account", "LANGSMITH_ENDPOINT": "http://127.0.0.1:18318",
    }
    (runtime / "spring.properties").write_text(
        "".join(f"{key}={value}\n" for key, value in settings.items()), encoding="utf-8", newline="\n",
    )
    print("Configured isolated runtime; credentials are local and must not be published.")


async def snapshot(runtime: Path) -> None:
    destination = runtime / "snapshot.json"
    if destination.exists():
        raise ValueError("Snapshot already exists")
    spring, search = await asyncio.gather(rows(SOURCE_SPRING, "places", "id"), rows(SOURCE_SEARCH, "place_embeddings", "place_id"))
    frozen_path = ROOT / "Evaluation/datasets/v1.4.0/generated/corpus.json"
    frozen = read_json(frozen_path)
    frozen_places = {p["id"]: ExistingPlace.from_mapping(p).to_dict() for p in frozen}
    comparisons = {}
    for label, records in (("spring", spring), ("search", search)):
        actual = {ExistingPlace.from_mapping(p).place_id: ExistingPlace.from_mapping(p).to_dict() for p in records}
        comparisons[label] = {
            "count": len(actual), "content_sha256": fingerprint(actual),
            "missing_ids": sorted(frozen_places.keys() - actual.keys()),
            "extra_ids": sorted(actual.keys() - frozen_places.keys()),
            "changed_ids": sorted(identifier for identifier in actual.keys() & frozen_places.keys()
                                  if actual[identifier] != frozen_places[identifier]),
        }
    jar_source = ROOT / "Server/TravelMate/build/libs/TravelMate-0.0.1-SNAPSHOT.jar"
    shutil.copyfile(jar_source, runtime / "spring.jar")
    source_paths = sorted((ROOT / "Server/TravelMate/src").rglob("*.java"))
    source_paths += sorted((ROOT / "embedding-server/app").rglob("*.py"))
    source_paths += sorted((ROOT / "embedding-server/routers").rglob("*.py"))
    document = {
        "created_at": datetime.now(UTC).isoformat(), "commit": await command("git", "-C", str(ROOT), "rev-parse", "HEAD"),
        "frozen_corpus_sha256": file_sha256(frozen_path), "comparisons": comparisons,
        "frozen_content_sha256": fingerprint(frozen_places),
        "spring_rows": spring, "search_rows": search,
        "spring_rows_sha256": fingerprint(spring), "search_rows_sha256": fingerprint(search),
        "jar_sha256": file_sha256(runtime / "spring.jar"),
        "source_file_sha256": {p.relative_to(ROOT).as_posix(): file_sha256(p) for p in source_paths},
    }
    write_json(destination, document)
    write_json(runtime / "corpus-comparison.json", {key: document[key] for key in (
        "commit", "frozen_corpus_sha256", "frozen_content_sha256", "comparisons", "spring_rows_sha256", "search_rows_sha256", "jar_sha256"
    )})
    print(json.dumps(document["comparisons"], ensure_ascii=False))


def preserved_evidence(archive: Path, search_rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    previous = archive / "v7-integration-v1/20261101-01"
    candidates = list((previous / "sonar/g").glob("394*/requests/*/*/record.json"))
    if len(candidates) != 1:
        raise ValueError("Expected the single previously approved real P09 archive; no substitutes permitted")
    record_path, = candidates
    approval_path = previous / "approval-P09.json"
    bundle, _, record = load_record(record_path)
    approved = reviewed_chunks(record_path, approval_path)
    place, = bundle.places
    current = next(p for p in search_rows if p["place_id"] == place.place_id)
    if ExistingPlace.from_mapping(current).source_fingerprint != place.source_fingerprint:
        raise ValueError("Preserved evidence place fingerprint differs from imported corpus")
    cache_path = archive / "general-relation-retrieval-v1/20261101-01/embedding-cache.json"
    publication = read_json(ROOT / "Evaluation/runs/contextual/general-relation-retrieval-v1/20261101-01/publication.json")
    expected_cache = publication["local_file_sha256"]["embedding-cache.json"]
    if file_sha256(cache_path) != expected_cache:
        raise ValueError("Preserved embedding cache differs from its published hash")
    cache = read_json(cache_path)
    active = select_active(place.place_id, approved)
    missing = [chunk.chunk_id for chunk in active if chunk.embedding_text not in cache]
    if missing:
        raise ValueError(f"Saved chunk vectors missing; no inference fallback: {missing}")
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in (
        "retrieval_source_versions", "retrieval_chunks", "retrieval_chunk_contexts", "place_active_chunks", "retrieval_relation_embeddings"
    )}
    for source in bundle.sources:
        tables["retrieval_source_versions"].append({"source_id": source.source_id, "source_version": source.source_version,
                                                   "document": source.to_dict(), "stored_at": record["created_at"]})
    for chunk in approved:
        tables["retrieval_chunks"].append({"chunk_id": chunk.chunk_id, "source_id": chunk.source.source_id,
            "source_version": chunk.source.source_version, "start_offset": chunk.start, "end_offset": chunk.end,
            "splitter_version": chunk.splitter_version, "chunk_text": chunk.chunk_text})
        tables["retrieval_chunk_contexts"].append({"chunk_id": chunk.chunk_id, "context_version": chunk.context_version,
            "document": chunk.to_dict(), "embedding": vector_text(cache[chunk.embedding_text]),
            "embedding_model": "BAAI/bge-m3", "stored_at": record["created_at"]})
    for slot, chunk in enumerate(active, 1):
        tables["place_active_chunks"].append({"place_id": place.place_id, "slot": slot, "chunk_id": chunk.chunk_id,
                                            "context_version": chunk.context_version, "role": chunk.active_role(place.place_id)})
    missing_relations = []
    for entry in relation_embedding_inputs(active):
        if entry.text not in cache:
            missing_relations.append({"chunk_id": entry.chunk_id, "relation_index": entry.relation_index})
            continue
        tables["retrieval_relation_embeddings"].append({"chunk_id": entry.chunk_id, "context_version": entry.context_version,
            "relation_index": entry.relation_index, "representation_version": "relation-quote-vector-v1",
            "evidence": entry.evidence, "embedding": vector_text(cache[entry.text]), "embedding_model": "BAAI/bge-m3",
            "stored_at": record["created_at"]})
    report = {"record": str(record_path), "record_sha256": file_sha256(record_path),
        "approval_sha256": file_sha256(approval_path), "cache_sha256": file_sha256(cache_path),
        "place_id": place.place_id, "place_fingerprint": place.source_fingerprint,
        "prompt_version": record["prompt_version"], "validation_version": record["validation_version"],
        "table_counts": {name: len(records) for name, records in tables.items()},
        "missing_relation_vectors": missing_relations,
        "b_case_place_evidence": {"311": EvidenceStatus.MISSING, "378": EvidenceStatus.MISSING},
        "synthetic_controls_imported": False, "new_evidence_or_vectors_generated": False}
    return tables, report


def vector_text(vector: list[float]) -> str:
    import math
    if len(vector) != 1024 or not all(math.isfinite(value) for value in vector):
        raise ValueError("Invalid preserved BGE vector")
    return "[" + ",".join(map(str, vector)) + "]"


async def load(runtime: Path, archive: Path) -> None:
    document = read_json(runtime / "snapshot.json")
    for comparison in document["comparisons"].values():
        if any(comparison[field] for field in ("missing_ids", "extra_ids", "changed_ids")):
            raise ValueError("Corpus content mismatch; inspect corpus-comparison.json before importing")
    evidence, evidence_report = preserved_evidence(archive, document["search_rows"])
    for target, table in ((TARGET_SPRING, "places"), (TARGET_SEARCH, "place_embeddings")):
        if int(await sql(target, f"SELECT count(*) FROM {table};")):
            raise ValueError("Evaluation target is not empty; imports never overwrite existing rows")
    migration = (ROOT / "Docker/migrations/20261025_place_recommendation_messaging.sql").read_text(encoding="utf-8")
    plan_migration = (ROOT / "Docker/migrations/20261013_add_planning_context.sql").read_text(encoding="utf-8")
    # The source tree schema is applied only to empty, explicitly named evaluation databases.
    await sql(TARGET_SPRING, plan_migration.replace("BEGIN;", "").replace("COMMIT;", "") + "\n" + migration.replace("BEGIN;", "").replace("COMMIT;", ""), write=True)
    # Replaying a preserved snapshot must not create fresh place-change/indexing events.
    spring_insert = "ALTER TABLE places DISABLE TRIGGER USER;\n"
    spring_insert += insert_records("places", document["spring_rows"], identity=True)
    spring_insert += "\nALTER TABLE places ENABLE TRIGGER USER;"
    spring_insert += "\nSELECT setval(pg_get_serial_sequence('places','id'), (SELECT max(id) FROM places));"
    spring_insert += f"\nINSERT INTO users(uid,user_id,email,nickname,role,status,provider) VALUES ('{EVALUATION_USER}','b-eval','b-eval@example.invalid','B evaluation','ROLE_BASE','ACTIVE','LOCAL');"
    await sql(TARGET_SPRING, spring_insert, write=True)
    restored_search = [{**row, "chunk_generation": 0} for row in document["search_rows"]]
    search_insert = insert_records("place_embeddings", restored_search)
    search_insert += "\n" + "\n".join(insert_records(table, records) for table, records in evidence.items())
    await sql(TARGET_SEARCH, search_insert, write=True)
    write_json(runtime / "evidence-inventory.json", evidence_report)
    print(json.dumps(evidence_report["table_counts"]))


async def verify(runtime: Path) -> None:
    document = read_json(runtime / "snapshot.json")
    spring, search = await asyncio.gather(rows(TARGET_SPRING, "places", "id"), rows(TARGET_SEARCH, "place_embeddings", "place_id"))
    original_search_columns = set(document["search_rows"][0])
    imported_search = [{key: row[key] for key in sorted(original_search_columns)} for row in search]
    result = {
        "spring_rows_match_snapshot": fingerprint(spring) == document["spring_rows_sha256"],
        "search_original_columns_match_snapshot": fingerprint(imported_search) == document["search_rows_sha256"],
        "spring_place_count": len(spring), "search_place_count": len(search),
        "pending_spring_outbox": int(await sql(TARGET_SPRING, "SELECT (SELECT count(*) FROM place_change_outbox WHERE published_at IS NULL)+(SELECT count(*) FROM recommendation_request_outbox WHERE published_at IS NULL);")),
        "pending_search_jobs": int(await sql(TARGET_SEARCH, "SELECT (SELECT count(*) FROM place_index_jobs WHERE status IN ('PENDING','RUNNING'))+(SELECT count(*) FROM recommendation_requests WHERE status IN ('PENDING','RUNNING'))+(SELECT count(*) FROM recommendation_result_outbox WHERE published_at IS NULL);")),
        "source_versions": sorted({row["source_version"] for row in search}),
        "index_config_versions": sorted({row["index_config_version"] for row in search}),
        "active_evidence": len(await rows(TARGET_SEARCH, "place_active_chunks", "place_id")),
        "ranking_scores_comparable": False,
        "ranking_limitations": ["Evidence availability depends on explicitly preserved records; original fields do not have chunk vectors.",
                                "CPU cross_encoder_predict differs from the old running autocast_fp16 service; no ranking equivalence evaluation was run.",
                                "The full frozen persona/context is not forwarded by this API contract."],
        "inference_calls": 0, "search_executions": 0,
    }
    write_json(runtime / "database-verification.json", result)
    if not result["spring_rows_match_snapshot"] or not result["search_original_columns_match_snapshot"]:
        raise ValueError("Imported corpus/vector bytes differ from the source snapshot")
    if result["pending_spring_outbox"] or result["pending_search_jobs"]:
        raise ValueError("Pending jobs would trigger unintended indexing or search")
    print(json.dumps(result, ensure_ascii=False))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", type=Stage, choices=list(Stage))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--archive", type=Path)
    arguments = parser.parse_args()
    runtime = arguments.runtime.resolve()
    if arguments.stage == Stage.CONFIGURE:
        if arguments.profile is None:
            parser.error("configure requires --profile")
        configure(runtime, arguments.profile)
        return
    stages = {Stage.SNAPSHOT: lambda: snapshot(runtime), Stage.LOAD: lambda: load(runtime, arguments.archive),
              Stage.VERIFY: lambda: verify(runtime)}
    if arguments.stage == Stage.LOAD and arguments.archive is None:
        parser.error("load requires --archive")
    await stages[arguments.stage]()


if __name__ == "__main__":
    asyncio.run(main())
