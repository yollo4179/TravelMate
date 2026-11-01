"""검수한 고정 청크·보존 벡터로 기존 검색과 이동 인용 벡터 경로를 비교한다."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import sys
import time
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse
from unittest.mock import patch
import uuid

import asyncpg
import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "embedding-server"))
from app.contextual.artifacts import load_record
from app.contextual.observation_search import ObservationFilter
from app.contextual.pipeline import index_embedding_inputs, select_active
from app.contextual.ranking import EvidenceCount, build_pairs, rank_places
from app.contextual.relation_vectors import relation_embedding_inputs
from app.contextual.repository import activate_chunks, store_relation_embeddings
from app.contextual.review import approval_document, reviewed_chunks
from app.enrichment.artifacts import write_json
from app.enrichment.repository import ensure_schema
from Evaluation.tracks.contextual.v7_search import distractors, portable


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserved_hashes(root: Path) -> dict[str, str]:
    manifest = json.loads((root / "publication.json").read_text(encoding="utf-8"))
    entries = {name: expected for name, expected in manifest["local_file_sha256"].items()}
    for name, expected in entries.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or sha256(path) != expected:
            raise ValueError("원본 보존 파일 해시 불일치")
    return {**entries, "publication.json": sha256(root / "publication.json")}


def load_inputs(previous: Path, processed: Path, output: Path) -> tuple[dict, list, Any, list[dict[str, Any]]]:
    summary = json.loads((previous / "sonar/generation-summary.json").read_text(encoding="utf-8"))
    places = {}
    approved = []
    for result in summary["results"]:
        path = portable(result["record"], previous)
        bundle, _, _ = load_record(path)
        places.update({place.place_id: place for place in bundle.places})
        if result["id"] == "P09":
            approved.extend(reviewed_chunks(path, previous / "approval-P09.json"))
    replay = json.loads((processed / "revalidation.json").read_text(encoding="utf-8"))
    original_root = PureWindowsPath(json.loads((processed / "publication.json").read_text(encoding="utf-8"))["local_access"])
    control = next(row for row in replay["results"] if row["id"] == "CONTROL")
    path = processed / Path(*PureWindowsPath(control["processed_record"]).relative_to(original_root).parts)
    _, controls, _ = load_record(path)
    supporting = next(chunk for chunk in controls if chunk.source.title == "mixed-supporting")
    relation, = supporting.relations
    if (supporting.subject_place_ids != {101}
            or {"place_id": 202, "role": "mentioned"} not in supporting.place_refs
            or relation["origin"] != {"place_id": 101, "name": "A공원"}
            or relation["destination"] != {"place_id": 202, "name": "B공원"}
            or relation["importance"] != "supporting"
            or relation["evidence"] != {"start": 15, "end": 35, "quote": "관람 후 B공원으로 걸어갈 수 있다."}):
        raise ValueError("고정 통제 문장의 의미 검수 조건 불일치")
    write_json(output / "approval-CONTROL-v5.json", approval_document(path, [chunk.chunk_id for chunk in controls], "버전을 아는 에이전트의 합성 원문·주체·방향·supporting 검수"))
    # 이전 비교와 같은 순서로 상한을 적용해 B의 44번째 관계를 임의로 앞에 넣지 않는다.
    controls_without_supporting = [chunk for chunk in controls if chunk.chunk_id != supporting.chunk_id]
    negative_places, negatives = distractors()
    places.update(negative_places)
    chunks = controls_without_supporting + approved + negatives + [supporting]
    questions = json.loads((previous / "search-plan.json").read_text(encoding="utf-8"))["questions"]
    return places, chunks, supporting, questions


def saved_score_cache(previous: Path, questions: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    queries = {question["id"]: question["query"] for question in questions}
    summary = json.loads((previous / "search-summary.json").read_text(encoding="utf-8"))
    cache = {}
    for result in summary["results"]:
        for row in result["ranked_places"]:
            cache[(queries[result["id"]], row["text"])] = float(row["score"])
    return cache


async def rerank_missing(
    client: httpx.AsyncClient,
    query: str,
    texts: list[str],
    cache: dict[tuple[str, str], float],
    calls: list[dict[str, Any]],
) -> list[float]:
    missing = list(dict.fromkeys(text for text in texts if (query, text) not in cache))
    if missing:
        started = time.perf_counter()
        response = await client.post("/rerank", json={"query": query, "texts": missing})
        response.raise_for_status()
        values = response.json()["scores"]
        if len(values) != len(missing) or not all(math.isfinite(score) for score in values):
            raise ValueError("리랭킹 점수 계약 불일치")
        calls.append({"query": query, "texts": missing, "scores": values, "elapsed_ms": (time.perf_counter() - started) * 1000})
        cache.update({(query, text): score for text, score in zip(missing, values, strict=True)})
    return [cache[(query, text)] for text in texts]


async def build_database(pool: Any, places: dict, selections: dict, cache: dict) -> None:
    await pool.execute((ROOT / "Docker/search-init/01-search-schema.sql").read_text(encoding="utf-8"))
    await ensure_schema(pool)
    for place in places.values():
        mapping = place.to_dict()
        columns = list(mapping)
        await pool.execute("INSERT INTO place_embeddings(" + ",".join(columns) + ",source_version,latest_seen_version) VALUES("
                           + ",".join(f"${index + 1}" for index in range(len(columns))) + ",1,1)", *mapping.values())
    async with pool.acquire() as connection:
        async with connection.transaction():
            for identifier, selected in selections.items():
                texts, primary = index_embedding_inputs(places[identifier], selected)
                await activate_chunks(connection, identifier, selected, [cache[chunk.embedding_text] for chunk in selected])
                inputs = relation_embedding_inputs(selected)
                await store_relation_embeddings(connection, inputs, [cache[entry.text] for entry in inputs])
                await connection.execute("UPDATE place_embeddings SET embedding=$2::vector WHERE place_id=$1", identifier,
                                         "[" + ",".join(map(str, cache[texts[primary]])) + "]")


async def evaluate_case(runtime: Any, question: dict, selections: dict, vector: list[float], client: httpx.AsyncClient,
                        cache: dict, calls: list, phase: str) -> dict[str, Any]:
    vector_text = "[" + ",".join(map(str, vector)) + "]"
    observation = ObservationFilter.from_mapping(question["filters"])
    started = time.perf_counter()
    candidates = await runtime._retrieve_candidates({"filters": {"observation": question["filters"]}}, vector_text)
    candidate_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    expanded = await runtime._retrieve_evidence(candidates, vector_text, EvidenceCount.TWO, observation=observation)
    expansion_ms = (time.perf_counter() - started) * 1000
    pairs = build_pairs(candidates, expanded, EvidenceCount.TWO)
    scores = await rerank_missing(client, question["query"], [pair.text for pair in pairs], cache, calls) if pairs else []
    ranked = rank_places(candidates, pairs, scores) if pairs else []
    expected, target = question["target_chunk"], question["target_place"]
    winner = next((row for row, _ in ranked if row["place_id"] == target), None)
    return {"phase": phase, "id": question["id"], "candidate_count": len(candidates), "rerank_pairs": len(pairs),
            "target_indexed": any(chunk.chunk_id == expected for chunk in selections[target]) if expected else None,
            "target_candidate_rank": next((index + 1 for index, row in enumerate(candidates) if row["place_id"] == target), None),
            "target_reached_reranker": any(candidates[pair.candidate_index]["place_id"] == target and pair.evidence and pair.evidence["chunk_id"] == expected for pair in pairs) if expected else None,
            "target_final_rank": next((index + 1 for index, (row, _) in enumerate(ranked) if row["place_id"] == target), None),
            "target_representative_correct": bool(winner and winner["evidence"]["chunk_id"] == expected) if expected else None,
            "target_retrieval_path": winner.get("evidence", {}).get("retrieval_path") if winner else None,
            "sql_candidate_ms": candidate_ms, "sql_expansion_ms": expansion_ms,
            "candidate_place_ids": [row["place_id"] for row in candidates],
            "ranked_places": [{"place_id": row["place_id"], "score": score, "text": row["description"],
                               "chunk_id": row["evidence"]["chunk_id"], "retrieval_path": row["evidence"].get("retrieval_path")}
                              for row, score in ranked]}


async def run(previous: Path, processed: Path, output: Path, model_url: str) -> Path:
    host, database = os.environ["PGHOST"], os.environ["PGDATABASE"]
    if not host.startswith("tm-v7-eval-") or not database.startswith("contextual_v7_eval"):
        raise ValueError("폐기용 DB 외에는 연결하지 않습니다")
    if urlparse(model_url).hostname not in ("travelmate-embedding", "127.0.0.1", "localhost"):
        raise ValueError("기존 로컬 모델 서버만 허용합니다")
    if (output / "comparison-plan.json").exists():
        raise ValueError("기존 비교를 자동 재실행하지 않습니다")
    originals = {"previous": preserved_hashes(previous), "processed": preserved_hashes(processed)}
    places, chunks, supporting, questions = load_inputs(previous, processed, output)
    selections = {identifier: select_active(identifier, chunks) for identifier in places}
    embedding_cache = json.loads((previous / "embedding-cache.json").read_text(encoding="utf-8"))
    base_texts = [text for identifier, selected in selections.items() for text in index_embedding_inputs(places[identifier], selected)[0]]
    if any(text not in embedding_cache for text in base_texts + [question["query"] for question in questions]):
        raise ValueError("기준 청크·질의 벡터가 보존 캐시에 없습니다")
    relation_texts = list(dict.fromkeys(entry.text for selected in selections.values() for entry in relation_embedding_inputs(selected)))
    missing = [text for text in relation_texts if text not in embedding_cache]
    score_cache = saved_score_cache(previous, questions)
    cache_before = len(score_cache)
    b_eligible = [chunk for chunk in chunks if 202 in chunk.index_place_ids]
    write_json(output / "comparison-plan.json", {"questions": questions,
        "phases": ["chunk-only", "chunk-and-relation-v1"], "candidate_limit": 30, "evidence_per_place": 2, "active_limit": 20,
        "selected_chunk_ids": {str(key): [chunk.chunk_id for chunk in value] for key, value in selections.items()},
        "negative_fixtures": 40, "reviewed_real_and_control_chunks": len(chunks) - 40,
        "b_eligible": len(b_eligible), "b_active": len(selections[202]),
        "b_target_eligible_position": next(index + 1 for index, chunk in enumerate(b_eligible) if chunk.chunk_id == supporting.chunk_id),
        "new_embedding_texts": missing, "originals": originals, "cached_query_text_scores": cache_before,
        "fusion": "같은 활성 청크의 전체 벡터와 방향에 맞는 관계 인용 벡터 중 최대 cosine. 장소 중복 제거 후 Top-30. 합산 없음.",
        "new_sonar_calls": 0, "production_database_writes": 0, "semantic_review": "합성 CONTROL 4개는 버전을 아는 에이전트 검수. 실제 P09는 기존 승인 8개만 재사용."})
    calls = []
    async with httpx.AsyncClient(base_url=model_url, timeout=180, trust_env=False) as client:
        health_response = await client.get("/health")
        health_response.raise_for_status()
        health = health_response.json()
        if health.get("status") != "ok" or health.get("dim") != 1024:
            raise ValueError("기존 모델 서버 상태·차원이 다릅니다")
        if missing:
            response = await client.post("/embed", json={"texts": missing})
            response.raise_for_status()
            vectors = response.json()["embeddings"]
            if len(vectors) != len(missing) or any(len(vector) != 1024 or not all(math.isfinite(value) for value in vector) for vector in vectors):
                raise ValueError("이동 인용 임베딩 계약 불일치")
            embedding_cache.update(zip(missing, vectors, strict=True))
        write_json(output / "embedding-cache.json", embedding_cache)
        with patch.dict(sys.modules, {"app.embedder": SimpleNamespace(embedder=None), "app.reranker": SimpleNamespace(reranker=None)}):
            module = importlib.import_module("app.kafka_runtime")
        admin = await asyncpg.connect(host=host, user="postgres", database=database)
        schema = "relation_search_" + uuid.uuid4().hex
        await admin.execute(f"CREATE SCHEMA {schema}")
        pool = await asyncpg.create_pool(host=host, user="postgres", database=database, min_size=1, max_size=3,
                                        server_settings={"search_path": schema + ",public"})
        try:
            await build_database(pool, places, selections, embedding_cache)
            runtime = object.__new__(module.KafkaRuntime)
            runtime.database_pool = pool
            results = []
            for phase in ("chunk-only", "chunk-and-relation-v1"):
                runtime.use_relation_vectors = phase == "chunk-and-relation-v1"
                for question in questions:
                    result = await evaluate_case(runtime, question, selections, embedding_cache[question["query"]], client, score_cache, calls, phase)
                    results.append(result)
                    print(json.dumps({key: value for key, value in result.items() if key not in ("ranked_places", "candidate_place_ids")}, ensure_ascii=False), flush=True)
            vector_rows = await pool.fetchval("SELECT count(*) FROM retrieval_relation_embeddings")
        finally:
            await pool.close()
            await admin.execute(f"DROP SCHEMA {schema} CASCADE")
            await admin.close()
    if preserved_hashes(previous) != originals["previous"] or preserved_hashes(processed) != originals["processed"]:
        raise ValueError("비교 중 이전 아카이브가 변경됐습니다")
    write_json(output / "new-rerank-calls.json", calls)
    report = {"results": results, "health": health, "search_executions": len(results), "evidence_per_place": 2,
              "candidate_limit": 30, "active_limit": 20, "b_eligible": len(b_eligible), "b_active": len(selections[202]),
              "target_in_b_active": supporting in selections[202], "relation_vector_rows": vector_rows,
              "new_embedding_calls": int(bool(missing)), "new_embedding_texts": len(missing),
              "new_rerank_calls": len(calls), "new_rerank_texts": sum(len(call["texts"]) for call in calls),
              "reused_embedding_texts": len(embedding_cache) - len(missing),
              "available_saved_query_text_scores": cache_before, "new_sonar_calls": 0, "production_database_writes": 0,
              "note": "고정한 감독 검증과 합성 스트레스 자료다. 일반 검색 성능이나 운영 개선의 증거가 아니다.",
              "latency_limit": "질의·청크 벡터와 기존 리랭킹 점수를 재사용했다. SQL 단회 시간만 기록하며 전체 지연 비교·성능 벤치마크로 해석하지 않는다."}
    write_json(output / "comparison.json", report)
    return output / "comparison.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--processed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-url", required=True)
    args = parser.parse_args()
    print(asyncio.run(run(args.previous, args.processed, args.output, args.model_url)))


if __name__ == "__main__":
    main()
