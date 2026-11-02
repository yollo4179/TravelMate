"""끝점·이동 필터 없는 고정 질문을 기존 SQL과 일반 관계 검색에서 비교한다."""
from __future__ import annotations

import argparse
import ast
import asyncio
from enum import StrEnum
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sys
import time
from types import MethodType, SimpleNamespace
from typing import Any
from unittest.mock import patch
from urllib.parse import urlparse
import uuid

import asyncpg
import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "embedding-server")]
from app.contextual.observation_search import ObservationFilter
from app.contextual.pipeline import select_active
from app.contextual.ranking import EvidenceCount, build_pairs, rank_places
from app.contextual.relation_vectors import relation_vector_sql
from app.enrichment.artifacts import write_json
from app.observability import tracer
from Evaluation.tracks.contextual.relation_vector_comparison import (
    build_database,
    load_inputs,
    preserved_hashes,
    rerank_missing,
    saved_score_cache,
)


class ComparisonPhase(StrEnum):
    FILTERED_RELATIONS = "baseline-1e646b33"
    GENERAL_RELATIONS = "general-relations"


def questions(supporting_id: str) -> list[dict[str, Any]]:
    unfiltered = (
        ("named-destination-no-filter", "B공원으로 걸어서 갈 수 있는 곳", 101, supporting_id),
        ("unnamed-movement", "다른 관광지로 걸어서 이동할 수 있는 공원", 101, None),
        ("mixed-scenery-movement", "야경 보고 나서 다른 관광지까지 걸어갈 수 있는 곳", 101, supporting_id),
        ("unnamed-connection", "주변 관광지와 연결된 곳", 101, None),
        ("scenery-no-filter", "야경이 아름다운 공원", 101, supporting_id),
        ("parking-no-filter", "청담도로공원 주차장은 무료인가요", 394, None),
    )
    return [
        {"id": identifier, "query": query, "filters": {}, "target_place": place_id, "target_chunk": chunk_id}
        for identifier, query, place_id, chunk_id in unfiltered
    ] + [
        {
            "id": "destination-filter",
            "query": "B공원으로 걸어서 갈 수 있는 곳",
            "filters": {"observation": {"destination_place_id": 202, "relation_importance": ["supporting"]}},
            "target_place": 101,
            "target_chunk": supporting_id,
        },
        {
            "id": "origin-only",
            "query": "A공원에서 걸어서 갈 다른 관광지",
            "filters": {"observation": {"origin_place_id": 101}},
            "target_place": 202,
            "target_chunk": None,
        },
        {
            "id": "inactive-supporting-destination",
            "query": "A공원에서 관람 후 걸어서 갈 수 있는 공원",
            "filters": {"observation": {"origin_place_id": 101, "relation_importance": ["supporting"]}},
            "target_place": 202,
            "target_chunk": supporting_id,
        },
    ]


def baseline_runtime(path: Path, pool: Any) -> Any:
    syntax = ast.parse(path.read_text(encoding="utf-8"))
    runtime_class = next(node for node in syntax.body if isinstance(node, ast.ClassDef) and node.name == "KafkaRuntime")
    methods = [
        node for node in runtime_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in ("_retrieve_candidates", "_retrieve_evidence")
    ]
    namespace = {
        "Any": Any,
        "ObservationFilter": ObservationFilter,
        "EvidenceCount": EvidenceCount,
        "relation_vector_sql": relation_vector_sql,
        "time": time,
        "tracer": tracer,
        "RETRIEVE_TOP_K": 30,
    }
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    runtime = SimpleNamespace(database_pool=pool, use_relation_vectors=True)
    for method in methods:
        setattr(runtime, method.name, MethodType(namespace[method.name], runtime))
    return runtime


async def evaluate(
    runtime: Any,
    question: dict[str, Any],
    vector: list[float],
    client: httpx.AsyncClient,
    score_cache: dict[tuple[str, str], float],
    calls: list[dict[str, Any]],
    phase: ComparisonPhase,
) -> dict[str, Any]:
    vector_text = "[" + ",".join(map(str, vector)) + "]"
    candidates = await runtime._retrieve_candidates({"filters": question["filters"]}, vector_text)
    expanded = await runtime._retrieve_evidence(
        candidates,
        vector_text,
        EvidenceCount.TWO,
        observation=ObservationFilter.from_mapping(question["filters"].get("observation")),
    )
    pairs = build_pairs(candidates, expanded, EvidenceCount.TWO)
    scores = await rerank_missing(client, question["query"], [pair.text for pair in pairs], score_cache, calls) if pairs else []
    ranked = rank_places(candidates, pairs, scores) if pairs else []
    target = question["target_place"]
    winner = next((row for row, _ in ranked if row["place_id"] == target), None)
    target_pairs = [pair for pair in pairs if candidates[pair.candidate_index]["place_id"] == target]
    return {
        "phase": phase,
        "id": question["id"],
        "candidate_count": len(candidates),
        "rerank_pairs": len(pairs),
        "target_candidate_rank": next((index + 1 for index, row in enumerate(candidates) if row["place_id"] == target), None),
        "target_final_rank": next((index + 1 for index, (row, _) in enumerate(ranked) if row["place_id"] == target), None),
        "target_representative_chunk": winner["evidence"]["chunk_id"] if winner else None,
        "target_supporting_chunk_reached": any(pair.evidence and pair.evidence["chunk_id"] == question["target_chunk"] for pair in target_pairs) if question["target_chunk"] else None,
        "target_relation_pair_count": sum(pair.evidence.get("retrieval_scope") == "relation" for pair in target_pairs if pair.evidence),
        "ranked_places": [
            {
                "place_id": row["place_id"],
                "score": score,
                "evidence": row["evidence"],
                "text": row["description"],
                "reranked_evidence_chunks": row["reranked_evidence_chunks"],
            }
            for row, score in ranked
        ],
    }


async def run(args: argparse.Namespace) -> None:
    database_url = os.environ["ENRICHMENT_TEST_DATABASE_URL"]
    target = urlparse(database_url)
    if not target.hostname or not target.hostname.startswith("tm-v7-eval-") or not target.path.startswith("/contextual_v7_eval"):
        raise ValueError("폐기용 DB 외에는 연결하지 않습니다")
    if urlparse(args.model_url).hostname not in ("travelmate-embedding", "localhost", "127.0.0.1"):
        raise ValueError("기존 로컬 모델 서비스만 사용합니다")
    if (args.output / "comparison-plan.json").exists():
        raise ValueError("기존 비교를 자동 재실행하지 않습니다")
    originals = {"previous": preserved_hashes(args.previous), "processed": preserved_hashes(args.processed)}
    places, chunks, supporting, _ = load_inputs(args.previous, args.processed, args.output)
    selections = {identifier: select_active(identifier, chunks) for identifier in places}
    cases = questions(supporting.chunk_id)
    embeddings = json.loads((args.relation_run / "embedding-cache.json").read_text(encoding="utf-8"))
    missing = list(dict.fromkeys(case["query"] for case in cases if case["query"] not in embeddings))
    previous_questions = json.loads((args.previous / "search-plan.json").read_text(encoding="utf-8"))["questions"]
    score_cache = saved_score_cache(args.previous, previous_questions)
    for call in json.loads((args.relation_run / "new-rerank-calls.json").read_text(encoding="utf-8")):
        score_cache.update({(call["query"], text): score for text, score in zip(call["texts"], call["scores"], strict=True)})
    write_json(args.output / "comparison-plan.json", {
        "questions": cases,
        "phases": list(ComparisonPhase),
        "baseline_runtime_sha256": hashlib.sha256(args.baseline_runtime.read_bytes()).hexdigest(),
        "candidate_limit": 30,
        "evidence_per_place": 2,
        "active_limit": 20,
        "selected_chunk_ids": {str(key): [chunk.chunk_id for chunk in selected] for key, selected in selections.items()},
        "new_embedding_texts": missing,
        "originals": originals,
        "review": "기존 승인 12개와 합성 방해 40개 재사용. 버전을 아는 개발 검수이며 블라인드 인간 평가가 아님.",
    })
    calls: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=args.model_url, timeout=180, trust_env=False) as client:
        health_response = await client.get("/health")
        health_response.raise_for_status()
        health = health_response.json()
        if health.get("status") != "ok" or health.get("dim") != 1024:
            raise ValueError("기존 모델 상태·차원 불일치")
        if missing:
            response = await client.post("/embed", json={"texts": missing})
            response.raise_for_status()
            vectors = response.json()["embeddings"]
            if len(vectors) != len(missing) or any(len(vector) != 1024 or not all(math.isfinite(value) for value in vector) for vector in vectors):
                raise ValueError("질문 임베딩 계약 불일치")
            embeddings.update(zip(missing, vectors, strict=True))
        write_json(args.output / "embedding-cache.json", embeddings)
        with patch.dict(sys.modules, {"app.embedder": SimpleNamespace(embedder=None), "app.reranker": SimpleNamespace(reranker=None)}):
            module = importlib.import_module("app.kafka_runtime")
        admin = await asyncpg.connect(database_url)
        schema = "general_relation_" + uuid.uuid4().hex
        await admin.execute(f"CREATE SCHEMA {schema}")
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3, server_settings={"search_path": schema + ",public"})
        try:
            await build_database(pool, places, selections, embeddings)
            baseline = baseline_runtime(args.baseline_runtime, pool)
            current = object.__new__(module.KafkaRuntime)
            current.database_pool = pool
            current.use_relation_vectors = True
            results = []
            for phase, runtime in ((ComparisonPhase.FILTERED_RELATIONS, baseline), (ComparisonPhase.GENERAL_RELATIONS, current)):
                for question in cases:
                    result = await evaluate(runtime, question, embeddings[question["query"]], client, score_cache, calls, phase)
                    results.append(result)
                    print(json.dumps({key: value for key, value in result.items() if key != "ranked_places"}, ensure_ascii=False), flush=True)
        finally:
            await pool.close()
            await admin.execute(f"DROP SCHEMA {schema} CASCADE")
            await admin.close()
    if preserved_hashes(args.previous) != originals["previous"] or preserved_hashes(args.processed) != originals["processed"]:
        raise ValueError("이전 원본 보존 파일이 변경됐습니다")
    write_json(args.output / "new-rerank-calls.json", calls)
    write_json(args.output / "comparison.json", {
        "results": results,
        "health": health,
        "search_executions": len(results),
        "new_embedding_calls": int(bool(missing)),
        "new_embedding_texts": len(missing),
        "new_rerank_calls": len(calls),
        "new_rerank_texts": sum(len(call["texts"]) for call in calls),
        "new_sonar_calls": 0,
        "production_database_writes": 0,
        "target_in_b_active": supporting in selections[202],
        "limit": "고정한 감독 합성 검증. 일반 검색 품질·전체 지연·운영 효과를 대표하지 않는다.",
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("previous", "processed", "relation-run", "output", "baseline-runtime"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--model-url", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
