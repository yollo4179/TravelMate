"""Compare captured runtime material offline, or capture read-only evidence with explicit targets."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import canonical_digest, digest, read_json, write_json
from common.execution.control import Operation, RunControl, RunMode, load_control
from tracks.search.holdout import check_frozen, new_output_directory

CORPUS_FIELDS = ("name", "description", "region", "city", "category", "latitude", "longitude", "tour_content_id")
MATERIAL_SECTIONS = frozenset({"places", "place_vectors", "active_chunks", "chunks", "contexts", "relations", "original_fields"})

MATERIAL_SQL = """
SELECT jsonb_build_object(
 'places', (SELECT coalesce(jsonb_agg(to_jsonb(p)-ARRAY['embedding','indexed_at'] ORDER BY place_id),'[]') FROM place_embeddings p),
 'place_vectors', (SELECT coalesce(jsonb_agg(jsonb_build_object('place_id',place_id,'dimension',vector_dims(embedding),'embedding_md5',md5(embedding::text)) ORDER BY place_id),'[]') FROM place_embeddings),
 'active_chunks', (SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY place_id,slot),'[]') FROM place_active_chunks a),
 'chunks', (SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY chunk_id),'[]') FROM retrieval_chunks c WHERE EXISTS(SELECT 1 FROM place_active_chunks a WHERE a.chunk_id=c.chunk_id)),
 'contexts', (SELECT coalesce(jsonb_agg((to_jsonb(c)-'embedding')||jsonb_build_object('embedding_md5',md5(embedding::text),'dimension',vector_dims(embedding)) ORDER BY chunk_id,context_version),'[]') FROM retrieval_chunk_contexts c WHERE EXISTS(SELECT 1 FROM place_active_chunks a WHERE a.chunk_id=c.chunk_id AND a.context_version=c.context_version)),
 'relations', (SELECT coalesce(jsonb_agg((to_jsonb(r)-'embedding')||jsonb_build_object('embedding_md5',md5(embedding::text),'dimension',vector_dims(embedding)) ORDER BY chunk_id,context_version,relation_index),'[]') FROM retrieval_relation_embeddings r WHERE EXISTS(SELECT 1 FROM place_active_chunks a WHERE a.chunk_id=r.chunk_id AND a.context_version=r.context_version)),
 'original_fields', (SELECT coalesce(jsonb_agg(to_jsonb(o) ORDER BY place_id),'[]') FROM place_original_field_evidence o)
);
"""

METADATA_SCRIPT = """
import ast,hashlib,json,os,pathlib,urllib.request
names=('EMBEDDING_MODEL','EMBEDDING_REVISION','RERANK_MODEL','RERANK_EXECUTION_STRATEGY','RERANK_BATCH_SIZE','RERANK_DIAGNOSTICS_ENABLED','CONTEXTUAL_RELATION_RETRIEVAL','CONTEXTUAL_RERANK_EVIDENCE_PER_PLACE','PRESERVED_ORIGINAL_EVIDENCE')
source=pathlib.Path('/app/app/kafka_runtime.py')
configuration=pathlib.Path('/app/app/config.py')
constants={target.id:ast.literal_eval(node.value) for node in ast.parse(configuration.read_text()).body if isinstance(node,ast.Assign) for target in node.targets if isinstance(target,ast.Name) and target.id in ('MODEL_NAME_EMBEDDING','MODEL_NAME_RERANKER')}
paths=('config.py','kafka_runtime.py','reranker.py','contextual/retrieval.py','contextual/ranking.py','contextual/relation_vectors.py','contextual/original_fields.py')
print(json.dumps({'health':json.loads(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=10).read()),'settings':{name:os.getenv(name) for name in names},'configured_models':constants,'search_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_files_sha256':{name:hashlib.sha256((pathlib.Path('/app/app')/name).read_bytes()).hexdigest() for name in paths},'cached_revisions':{p.parent.parent.name:p.read_text().strip() for p in pathlib.Path('/models/hub').glob('models--BAAI--*/refs/main')}}))
"""


def compare_runtime(
    *,
    corpus: list[dict[str, Any]],
    protocol: dict[str, Any],
    capture: dict[str, Any],
    expected_material: dict[str, Any],
    expected_configuration: dict[str, Any],
    expected_targets: dict[str, Any],
    corpus_sha256: str,
) -> dict[str, Any]:
    material = capture.get("search_material") or {}
    places = material.get("places") or []
    indexed = {place["place_id"]: place for place in places}
    frozen = {place["id"]: place for place in corpus}
    mismatches = [
        {"place_id": identifier, "fields": [name for name in CORPUS_FIELDS if indexed[identifier].get(name) != place.get(name)]}
        for identifier, place in frozen.items()
        if identifier in indexed and any(indexed[identifier].get(name) != place.get(name) for name in CORPUS_FIELDS)
    ]
    vectors = material.get("place_vectors") or []
    vector_metadata_matches = {row.get("place_id") for row in vectors} == set(frozen) and len(vectors) == len(frozen) and all(row.get("dimension") == 1024 and row.get("embedding_md5") for row in vectors)
    corpus_verified = (
        len(indexed) == len(places)
        and set(indexed) == set(frozen)
        and not mismatches
        and all(place.get("document_status") == "READY" for place in places)
        and vector_metadata_matches
    )
    targets_match = capture.get("targets") == expected_targets
    material_verified = set(material) == MATERIAL_SECTIONS and set(expected_material) == MATERIAL_SECTIONS and canonical_digest(material) == canonical_digest(expected_material)
    metadata = capture.get("metadata") or {}
    health = metadata.get("health") or {}
    comparison = protocol["comparison"]
    def stable_configuration(observed: dict[str, Any]) -> dict[str, Any]:
        return {**observed, "health": {name: value for name, value in (observed.get("health") or {}).items() if name != "reranker_inference_count"}}
    configuration_matches = stable_configuration(metadata) == stable_configuration(expected_configuration)
    configuration_verified = (
        targets_match and configuration_matches
        and health.get("status") == "ok"
        and health.get("reranker_execution_strategy") == comparison["reranking_strategy"]
        and health.get("reranker_configured_batch_size") == comparison["reranking_batch_size"]
        and health.get("reranker_effective_batch_size") == comparison["reranking_batch_size"]
        and health.get("cuda_available") is True
        and str(health.get("embedding_parameter_device", "")).startswith("cuda")
        and str(health.get("reranker_parameter_device", "")).startswith("cuda")
        and bool(metadata.get("cached_revisions", {}).get("models--BAAI--bge-m3"))
        and bool(metadata.get("cached_revisions", {}).get("models--BAAI--bge-reranker-v2-m3"))
        and bool(metadata.get("search_source_sha256"))
        and metadata.get("configured_models", {}).get("MODEL_NAME_EMBEDDING") == comparison["embedding_model"]
        and metadata.get("configured_models", {}).get("MODEL_NAME_RERANKER") == comparison["reranking_model"]
        and bool(metadata.get("source_files_sha256"))
    )
    live = capture.get("execution_mode") == RunMode.LIVE
    return {
        "schema_version": "search-runtime-verification-v2",
        "execution_mode": capture.get("execution_mode"), "targets": capture.get("targets"),
        "corpus_sha256": corpus_sha256,
        "corpus_verified": live and corpus_verified,
        "configuration_verified": live and configuration_verified,
        "search_material_verified": live and targets_match and material_verified,
        "comparison_checks": {"corpus_matches": corpus_verified, "configuration_matches": configuration_verified, "search_material_matches": material_verified, "targets_match": targets_match},
        "expected_place_count": len(frozen), "actual_place_count": len(places),
        "missing_place_ids": sorted(set(frozen) - set(indexed)), "additional_place_ids": sorted(set(indexed) - set(frozen)),
        "content_mismatches": mismatches,
        "search_material_sha256": canonical_digest(material), "expected_search_material_sha256": canonical_digest(expected_material),
        "metadata": metadata,
        "quality_status": "mock_regression_only" if not live else "runtime_checks_only",
        "limitations": ["Cached revisions and stored vector hashes are provenance observations, not proof of regenerated vectors or loaded weight identity.", "MOCK comparisons cannot authorize LIVE quality scoring.", "CPU/different precision is functional evidence and does not match this frozen GPU protocol.", "Request/turn/job observation and model/search quality are evaluated separately."],
    }


async def docker_read(control: RunControl, case_id: str, arguments: list[str]) -> dict[str, Any]:
    async def invoke() -> dict[str, Any]:
        process = await asyncio.create_subprocess_exec("docker", *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=control.settings.timeout_seconds)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode != 0:
            raise RuntimeError("Read-only Docker capture failed; no fallback target is selected")
        return {"stdout": stdout.decode("utf-8")}
    return await control.execute(Operation.RUNTIME_READ, case_id, {"command": ["docker", *arguments]}, invoke)


async def capture_runtime(control: RunControl) -> dict[str, Any]:
    if len(control.settings.case_ids) != 1:
        raise ValueError("Runtime capture requires one explicit environment observation ID")
    targets = control.settings.parameter("targets")
    required = {"embedding_container", "postgres_container", "database_user", "database"}
    if set(targets) != required or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) for value in targets.values()):
        raise ValueError("Explicit Docker/database target names are required; flags and inferred targets are forbidden")
    control.settings.require_capacity(Operation.RUNTIME_READ, 2)
    identifier = control.settings.case_ids[0]
    material = await docker_read(control, identifier, ["exec", targets["postgres_container"], "psql", "-X", "-U", targets["database_user"], "-d", targets["database"], "-At", "-v", "ON_ERROR_STOP=1", "-c", MATERIAL_SQL])
    metadata = await docker_read(control, identifier, ["exec", targets["embedding_container"], "python", "-c", METADATA_SCRIPT])
    return {"execution_mode": control.settings.mode.value, "targets": targets, "search_material": json.loads(material["stdout"]), "metadata": json.loads(metadata["stdout"])}


async def inspect_runtime(arguments: argparse.Namespace) -> None:
    check_frozen(arguments.dataset)
    if arguments.output_dir.exists():
        raise FileExistsError("Runtime evidence cannot overwrite an existing directory")
    if arguments.capture is not None:
        if arguments.config or arguments.mock_responses:
            raise ValueError("Offline capture review does not accept an execution config or transport")
        capture = read_json(arguments.capture)
        new_output_directory(arguments.output_dir)
        write_json(arguments.output_dir / "capture-provenance.json", {"mode": "OFFLINE_REVIEW", "input_sha256": digest(arguments.capture)})
    else:
        if arguments.config is None:
            raise ValueError("Live/MOCK capture requires an explicit execution configuration")
        control = load_control(arguments.config, arguments.output_dir, arguments.mock_responses)
        capture = await capture_runtime(control)
        write_json(arguments.output_dir / "capture.json", capture)
    protocol = read_json(arguments.dataset / "protocol.json")
    corpus_path = arguments.dataset / protocol["corpus_path"]
    expected = read_json(arguments.expected_runtime)
    report = compare_runtime(corpus=read_json(corpus_path), protocol=protocol, capture=capture, expected_material=read_json(arguments.expected_material), expected_configuration=expected["metadata"], expected_targets=expected["targets"], corpus_sha256=digest(corpus_path))
    report.update(dataset_manifest_sha256=digest(arguments.dataset / "manifest.json"), expected_runtime_sha256=digest(arguments.expected_runtime), expected_material_file_sha256=digest(arguments.expected_material))
    write_json(arguments.output_dir / "runtime.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--mock-responses", type=Path)
    parser.add_argument("--expected-runtime", type=Path, required=True)
    parser.add_argument("--expected-material", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    asyncio.run(inspect_runtime(parser.parse_args()))


if __name__ == "__main__":
    main()
