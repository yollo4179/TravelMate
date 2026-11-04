"""Record Docker runtime evidence and compare the complete frozen search corpus."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import digest, read_json, write_json
from tracks.search.holdout import DEFAULT_HOLDOUT, check_frozen, new_output_directory


def docker_output(arguments: list[str]) -> str:
    completed = subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


def inspect_runtime(dataset: Path, output: Path) -> dict[str, Any]:
    check_frozen(dataset)
    protocol = read_json(dataset / "protocol.json")
    expected = {place["id"]: place for place in read_json(dataset / protocol["corpus_path"])}
    sql = """
        SELECT coalesce(json_agg(row_to_json(candidate)), '[]'::json) FROM (
            SELECT place_id, name, description, region, city, category,
                   latitude, longitude, tour_content_id, document_status,
                   index_config_version, vector_dims(embedding) AS dimension
            FROM place_embeddings ORDER BY place_id
        ) candidate
    """
    live = {place["place_id"]: place for place in json.loads(docker_output([
        "exec", "travelmate-search-postgres", "psql", "-U", "travel_search",
        "-d", "travel_search_db", "-Atqc", sql,
    ]))}
    fields = ("name", "description", "region", "city", "category", "latitude", "longitude", "tour_content_id")
    mismatches = [
        {"place_id": identifier, "fields": [name for name in fields if live[identifier][name] != place[name]]}
        for identifier, place in expected.items()
        if identifier in live and any(live[identifier][name] != place[name] for name in fields)
    ]
    details = json.loads(docker_output(["inspect", "travelmate-embedding"]))[0]
    environment = dict(entry.split("=", 1) for entry in details["Config"]["Env"])
    selected_names = (
        "EMBEDDING_MODEL", "EMBEDDING_REVISION", "EMBEDDING_WEIGHTS_SHA256", "EMBEDDING_DEVICE",
        "RERANK_EXECUTION_STRATEGY", "RERANK_BATCH_SIZE", "RERANK_DIAGNOSTICS_ENABLED",
    )
    settings = {name: environment.get(name) for name in selected_names}
    revisions = json.loads(docker_output([
        "exec", "travelmate-embedding", "python", "-c",
        "import pathlib,json; root=pathlib.Path('/models/hub'); "
        "print(json.dumps({p.parent.parent.name:p.read_text().strip() for p in root.glob('models--BAAI--*/refs/main')}))",
    ]))
    health = json.loads(docker_output([
        "exec", "travelmate-embedding", "python", "-c",
        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())",
    ]))
    candidate_limit = docker_output([
        "exec", "travelmate-embedding", "python", "-c",
        "import pathlib,re; text=pathlib.Path('/app/app/kafka_runtime.py').read_text(); "
        "print(re.search(r'^RETRIEVE_TOP_K\\s*=\\s*(\\d+)',text,re.M).group(1))",
    ])
    corpus_verified = (
        set(live) == set(expected) and not mismatches
        and all(place["document_status"] == "READY" and place["dimension"] == 1024 for place in live.values())
        and all(place["index_config_version"] == "bge-m3-v1" for place in live.values())
    )
    comparison = protocol["comparison"]
    configuration_verified = (
        settings["EMBEDDING_MODEL"] == comparison["embedding_model"]
        and settings["RERANK_EXECUTION_STRATEGY"] == comparison["reranking_strategy"]
        and settings["RERANK_BATCH_SIZE"] == str(comparison["reranking_batch_size"])
        and settings["RERANK_DIAGNOSTICS_ENABLED"] == "false"
        and int(candidate_limit) == comparison["retrieval_candidate_limit"]
        and health.get("status") == "ok"
        and health.get("embedding_device") == health.get("reranker_device") == "cuda"
    )
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_manifest_sha256": digest(dataset / "manifest.json"),
        "embedding_revision": revisions.get("models--BAAI--bge-m3"),
        "reranker_revision": revisions.get("models--BAAI--bge-reranker-v2-m3"),
        "revision_evidence": "HF cache refs/main read after model startup; model names and embedding pin recorded separately",
        "gpu": health.get("gpu_name"),
        "corpus_verified": corpus_verified,
        "configuration_verified": configuration_verified,
        "frozen_corpus_sha256": digest(dataset / protocol["corpus_path"]),
        "expected_place_count": len(expected),
        "actual_place_count": len(live),
        "missing_place_ids": sorted(set(expected) - set(live)),
        "additional_place_ids": sorted(set(live) - set(expected)),
        "content_mismatches": mismatches,
        "verified_fields": fields,
        "index_config_versions": sorted({place["index_config_version"] for place in live.values()}),
        "vector_provenance_limit": "Index metadata and dimensions checked; individual vectors were not regenerated",
        "embedding_container_image_id": details["Image"],
        "runtime_settings": settings,
        "health": health,
        "retrieval_candidate_limit": int(candidate_limit),
    }
    new_output_directory(output)
    write_json(output / "runtime.json", report)
    print(json.dumps({name: report[name] for name in (
        "expected_place_count", "actual_place_count", "corpus_verified", "configuration_verified", "gpu",
    )}, ensure_ascii=False, indent=2))
    if not corpus_verified or not configuration_verified:
        raise ValueError("Runtime does not match the frozen protocol; see the saved runtime report")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    inspect_runtime(arguments.dataset, arguments.output_dir)


if __name__ == "__main__":
    main()
