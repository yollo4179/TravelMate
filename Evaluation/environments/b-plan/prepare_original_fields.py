"""Bind the two existing B anchors to frozen TourAPI fields without model calls."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path
import sys
from typing import Any
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare
from app.contextual.original_fields import FrozenSnapshot, attach_original_fields, description_evidence
from app.contextual.ranking import EvidenceCount, build_pairs, rank_places
from app.contextual.result_mapping import result_item
from app.enrichment.contracts import ExistingPlace, fingerprint

PLACE_IDS = (311, 378)


def frozen_descriptions() -> tuple[list[dict[str, Any]], FrozenSnapshot]:
    dataset = prepare.ROOT / "Evaluation/datasets/v1.4.0"
    snapshot_path = dataset / "source/snapshot.json"
    corpus_path = dataset / "generated/corpus.json"
    manifest_path = dataset / "manifest.json"
    original = prepare.read_json(snapshot_path)
    corpus = prepare.read_json(corpus_path)
    selected = [place for place in corpus if place["id"] in PLACE_IDS]
    if {place["id"] for place in selected} != set(PLACE_IDS):
        raise ValueError("Frozen B anchors are missing")
    for place in selected:
        source = next(row for row in original["places"] if row["id"] == place["id"])
        if source["description"] != place["description"] or source["tour_content_id"] != place["tour_content_id"]:
            raise ValueError("Generated corpus description differs from its frozen snapshot")
        if not any(row["tour_content_id"] == place["tour_content_id"] for row in original["tour_api_raw"]):
            raise ValueError("Frozen source snapshot has no matching TourAPI record")
    binding = FrozenSnapshot(
        version=prepare.read_json(manifest_path)["dataset_version"],
        snapshot_sha256=prepare.file_sha256(snapshot_path),
        corpus_sha256=prepare.file_sha256(corpus_path),
        manifest_sha256=prepare.file_sha256(manifest_path),
    )
    return selected, binding


class EvaluationPool:
    async def fetch(self, statement: str, identifiers: list[int]) -> list[dict[str, Any]]:
        if statement.strip().split()[0] != "SELECT" or identifiers != list(PLACE_IDS):
            raise ValueError("Only the fixed original-field binding query is allowed")
        binding = "ARRAY[" + ",".join(map(str, identifiers)) + "]"
        result = await prepare.sql(
            prepare.TARGET_SEARCH,
            "SELECT coalesce(jsonb_agg(to_jsonb(bound)), '[]'::jsonb) FROM (" + statement.replace("$1", binding) + ") bound;",
        )
        return json.loads(result)


async def prepare_fields(runtime: Path) -> None:
    selected, binding = frozen_descriptions()
    preserved = prepare.read_json(runtime / "snapshot.json")
    if binding.corpus_sha256 != preserved["frozen_corpus_sha256"]:
        raise ValueError("Evaluation runtime uses another frozen corpus")
    current = await prepare.rows(prepare.TARGET_SEARCH, "place_embeddings", "place_id")
    current_by_id = {row["place_id"]: row for row in current}
    documents = []
    records = []
    for source in selected:
        place = ExistingPlace.from_mapping(source)
        row = current_by_id[place.place_id]
        if ExistingPlace.from_mapping(row).source_fingerprint != place.source_fingerprint:
            raise ValueError("Evaluation place changed; do not bind an obsolete original")
        document = description_evidence(place, binding)
        documents.append(document)
        records.append({"place_id": place.place_id, "place_source_version": row["source_version"],
                        "place_fingerprint": place.source_fingerprint, "document": document})
    await prepare.sql(prepare.TARGET_SEARCH,
                      (prepare.ROOT / "embedding-server/app/contextual/schema.sql").read_text(encoding="utf-8"), write=True)
    await prepare.sql(prepare.TARGET_SEARCH,
                      prepare.insert_records("place_original_field_evidence", records).removesuffix(";") + " ON CONFLICT DO NOTHING;", write=True)
    stored = await prepare.rows(prepare.TARGET_SEARCH, "place_original_field_evidence", "place_id")
    if stored != records:
        raise ValueError("Stored original-field binding differs; imports do not overwrite earlier evidence")
    destination = runtime / "original-fields"
    destination.mkdir(exist_ok=True)
    prepare.write_json(destination / "evidence.json", documents)
    # These scores simulate ranking transport only; no query vector or reranker is evaluated.
    candidates = [{**row, "evidence": None, "semantic_score": 0.5, "place_id": source["id"]}
                  for source in selected for row in [current_by_id[source["id"]]]]
    attached = await attach_original_fields(EvaluationPool(), candidates)
    expanded = await attach_original_fields(EvaluationPool(), [
        {"place_id": row["place_id"], "source_version": row["source_version"], "evidence": None, "semantic_score": 0.5}
        for row in candidates
    ])
    pairs = build_pairs(attached, expanded, EvidenceCount.TWO)
    ranked = rank_places(attached, pairs, [0.5] * len(pairs))
    if [pair.text for pair in pairs] != [source["description"] for source in selected]:
        raise ValueError("Selected original was rewritten or replaced by generated context")
    items = [result_item(row, index, score) for index, (row, score) in enumerate(ranked, 1)]
    event = {"schema_version": 1, "request_id": str(uuid.uuid4()), "event_id": str(uuid.uuid4()),
             "event_type": "RECOMMENDATION_COMPLETED", "context_version": 0, "status": "COMPLETED", "items": items}
    prepare.write_json(destination / "mock-kafka-result.json", event)
    prepare.write_json(destination / "inventory.json", {
        "validation_scope": "MOCK_SCORES_REAL_EVALUATION_DB_FIELD_BINDING",
        "place_evidence": {str(identifier): prepare.EvidenceStatus.FIELD_READY for identifier in PLACE_IDS},
        "evidence_documents_sha256": fingerprint(documents), "new_embedding_calls": 0,
        "new_embedding_texts": 0, "vector_binding": "NOT_EMBEDDED", "candidate_embedding_lineage": "preserved_place_vector_only",
        "original_characters": {str(row["id"]): len(row["description"]) for row in selected},
        "mock_ranking_scores": [0.5] * len(pairs), "ranking_scores_comparable": False,
        "real_query_embedding_reranking_or_B_calls": 0,
    })
    print(json.dumps({"bound_place_ids": PLACE_IDS, "mock_selected_originals": len(pairs), "new_embedding_calls": 0}))


async def record_deployment(runtime: Path) -> None:
    destination = runtime / "original-fields"
    if not (destination / "inventory.json").exists():
        raise ValueError("Prepare and validate preserved originals before deploying")
    jar = destination / "spring.jar"
    source_jar = prepare.ROOT / "Server/TravelMate/build/libs/TravelMate-0.0.1-SNAPSHOT.jar"
    if jar.exists() and prepare.file_sha256(jar) != prepare.file_sha256(source_jar):
        raise ValueError("Use a new deployment version instead of overwriting the prepared JAR")
    shutil.copyfile(source_jar, jar)
    sources = sorted((prepare.ROOT / "Server/TravelMate/src").rglob("*.java"))
    sources += sorted((prepare.ROOT / "embedding-server/app").rglob("*.py"))
    sources += sorted((prepare.ROOT / "embedding-server/routers").rglob("*.py"))
    prepare.write_json(destination / "deployment.json", {
        "base_commit": await prepare.command("git", "-C", str(prepare.ROOT), "rev-parse", "HEAD"),
        "jar_path": jar.as_posix(), "jar_sha256": prepare.file_sha256(jar),
        "source_file_sha256": {p.relative_to(prepare.ROOT).as_posix(): prepare.file_sha256(p) for p in sources},
        "original_evidence_mode": "post-retrieval-field-v1", "no_actual_B_execution": True,
    })


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--record-deployment", action="store_true")
    arguments = parser.parse_args()
    runtime = arguments.runtime.resolve()
    if arguments.record_deployment:
        await record_deployment(runtime)
        return
    await prepare_fields(runtime)


if __name__ == "__main__":
    asyncio.run(main())
