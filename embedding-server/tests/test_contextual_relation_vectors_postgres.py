"""폐기용 DB에서 관계 벡터의 방향·활성 범위·원문 검증을 실제 실행한다."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from app.contextual.contracts import SearchChunk, SplitterVersion
from app.contextual.observation_search import ObservationFilter
from app.contextual.pipeline import normalize_source
from app.contextual.ranking import EvidenceCount, build_pairs
from app.contextual.relation_vectors import relation_embedding_inputs
from app.contextual.repository import activate_chunks, apply_bundle, ensure_schema, store_relation_embeddings
import test_contextual_supporting_postgres as supporting

V = [1.0] + [0.0] * 1023
OTHER = [0.0, 1.0] + [0.0] * 1022
VECTOR = "[" + ",".join(map(str, V)) + "]"


@unittest.skipUnless(os.environ.get("CONTEXTUAL_ISOLATED_DATABASE") == "1", "폐기용 DB를 명시해야 실행")
class RelationVectorPostgresTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = supporting.SupportingPostgresTests.asyncSetUp
    asyncTearDown = supporting.SupportingPostgresTests.asyncTearDown
    prepared = supporting.SupportingPostgresTests.prepared
    activate = supporting.SupportingPostgresTests.activate
    runtime = supporting.SupportingPostgresTests.runtime

    async def indexed(self) -> tuple[list[SearchChunk], object]:
        _, _, chunks = await self.prepared()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                for place_id in (394, 395):
                    await activate_chunks(connection, place_id, chunks, [OTHER])
                await store_relation_embeddings(connection, relation_embedding_inputs(chunks), [V])
        _, runtime, _ = self.runtime()
        runtime.use_relation_vectors = True
        return chunks, runtime

    async def test_directional_union_deduplicates_place_and_preserves_quote_for_expansion(self) -> None:
        chunks, runtime = await self.indexed()
        condition = ObservationFilter.from_mapping({"destination_place_id": 395, "relation_importance": ["supporting"]})
        candidates = await runtime._retrieve_candidates({"filters": {"observation": condition.to_dict()}}, VECTOR)
        self.assertEqual([row["place_id"] for row in candidates], [394])
        self.assertAlmostEqual(candidates[0]["semantic_score"], 1.0)
        self.assertEqual(candidates[0]["evidence"]["retrieval_path"], "relation")
        self.assertEqual(candidates[0]["evidence"]["retrieved_relation_index"], 0)
        expanded = await runtime._retrieve_evidence(candidates, VECTOR, EvidenceCount.TWO, observation=condition)
        pairs = build_pairs(candidates, expanded, EvidenceCount.TWO)
        self.assertEqual(len(pairs), 1)
        self.assertNotIn("야경", pairs[0].text)
        self.assertIn(chunks[0].relations[0]["evidence"]["quote"], pairs[0].text)
        reverse = await runtime._retrieve_candidates({"filters": {"observation": {"origin_place_id": 394}}}, VECTOR)
        self.assertEqual([row["place_id"] for row in reverse], [395])

    async def test_inactive_endpoint_and_wrong_direction_never_resurrect_from_stored_vectors(self) -> None:
        _, runtime = await self.indexed()
        self.assertEqual(await runtime._retrieve_candidates({"filters": {"observation": {"destination_place_id": 394}}}, VECTOR), [])
        await self.pool.execute("DELETE FROM place_active_chunks WHERE place_id=395")
        self.assertEqual(await runtime._retrieve_candidates({"filters": {"observation": {"origin_place_id": 394}}}, VECTOR), [])
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM retrieval_relation_embeddings"), 1)
        await self.pool.execute("UPDATE place_embeddings SET latest_seen_version=2 WHERE place_id=394")
        self.assertEqual(await runtime._retrieve_candidates({"filters": {"observation": {"destination_place_id": 395}}}, VECTOR), [])

    async def test_trigger_rejects_wrong_quote_wrong_index_and_wrong_positions(self) -> None:
        import asyncpg
        chunks, _ = await self.indexed()
        entry, = relation_embedding_inputs(chunks)
        for index, evidence in ((1, entry.evidence), (0, {**entry.evidence, "quote": "가깝고 편하다"}),
                                (0, {**entry.evidence, "start": 16})):
            with self.subTest(index=index, evidence=evidence):
                with self.assertRaises(asyncpg.CheckViolationError):
                    await self.pool.execute("INSERT INTO retrieval_relation_embeddings(chunk_id,context_version,relation_index,representation_version,evidence,embedding) VALUES($1,$2,$3,'invalid-test',$4::jsonb,$5::vector)",
                                            uuid.UUID(entry.chunk_id), entry.context_version, index, json.dumps(evidence), VECTOR)
        await ensure_schema(self.pool)
        await ensure_schema(self.pool)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM retrieval_relation_embeddings"), 1)

    async def test_best_vector_from_wrong_relation_does_not_bypass_destination_filter(self) -> None:
        await self.pool.execute("INSERT INTO place_embeddings(place_id,source_version,latest_seen_version,name) VALUES(396,1,1,'C공원')")
        text = "A공원은 야경이 좋고 B공원으로 걸어갈 수 있으며 C공원까지 차량으로만 이동한다."
        source = normalize_source({"source_type": "review", "title": "서로 다른 이동 관계", "text": text,
                                   "metadata": {"source_url": "https://example.org/multiple-routes", "capture_scope": "full_text"}})
        quotes = ("B공원으로 걸어갈 수 있으며", "C공원까지 차량으로만 이동한다.")
        relations = [{"type": "movement", "importance": "supporting", "origin": {"place_id": 394, "name": "A공원"},
                      "destination": {"place_id": place_id, "name": name}, "conditions": [],
                      "evidence": {"start": text.index(quote), "end": text.index(quote) + len(quote), "quote": quote}}
                     for place_id, name, quote in ((395, "B공원", quotes[0]), (396, "C공원", quotes[1]))]
        chunk = SearchChunk(source, 0, len(text), "A의 야경과 B/C로 가는 서로 다른 이동 내용이다.",
                            [{"place_id": 394, "role": "subject"}, {"place_id": 395, "role": "mentioned"}, {"place_id": 396, "role": "mentioned"}],
                            {"provider": "synthetic-multi-edge"}, [], [], SplitterVersion.SENTENCE, "landscape", relations)
        async with self.pool.acquire() as connection:
            await activate_chunks(connection, 394, [chunk], [OTHER])
            await store_relation_embeddings(connection, relation_embedding_inputs([chunk]), [[1.0, 1.0] + [0.0] * 1022, V])
        _, runtime, _ = self.runtime()
        runtime.use_relation_vectors = True
        candidates = await runtime._retrieve_candidates({"filters": {"observation": {"destination_place_id": 395}}}, VECTOR)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["evidence"]["retrieved_relation_index"], 0)
        self.assertAlmostEqual(candidates[0]["semantic_score"], 2 ** -0.5, places=6)
        self.assertNotIn(quotes[1], candidates[0]["description"])

    async def test_worker_enabled_indexes_quotes_inside_existing_generation_transaction(self) -> None:
        path, approval, _ = await self.prepared()
        await apply_bundle(self.pool, path, review_path=approval)
        module, runtime, model = self.runtime()
        runtime.use_relation_vectors = True
        inputs = []
        def embed(texts: list[str]) -> list[list[float]]:
            inputs.extend(texts)
            return [V for _ in texts]
        model.embed = embed
        job = await self.pool.fetchrow("SELECT * FROM place_index_jobs WHERE place_id=394")
        with patch.object(module, "embedder", model):
            await runtime._index_place_job(job)
        self.assertIn("관람 후 B공원으로 걸어갈 수 있다.", inputs)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM retrieval_relation_embeddings"), 1)
        self.assertLessEqual(await self.pool.fetchval("SELECT count(*) FROM place_active_chunks WHERE place_id=394"), 20)
        self.assertEqual(await self.pool.fetchval("SELECT status FROM place_index_jobs WHERE place_id=394"), "SUCCEEDED")

    async def test_superseded_worker_generation_does_not_store_relation_vectors(self) -> None:
        path, approval, _ = await self.prepared()
        await apply_bundle(self.pool, path, review_path=approval)
        module, runtime, model = self.runtime()
        runtime.use_relation_vectors = True
        calls = 0
        async def infer(function: Callable[[], Any]) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                await self.pool.execute("UPDATE place_embeddings SET chunk_generation=chunk_generation+1 WHERE place_id=394")
            return function()
        job = await self.pool.fetchrow("SELECT * FROM place_index_jobs WHERE place_id=394")
        with patch.object(module, "embedder", model), patch.object(module.to_thread, "run_sync", side_effect=infer):
            await runtime._index_place_job(job)
        self.assertEqual(await self.pool.fetchval("SELECT status FROM place_index_jobs WHERE place_id=394"), "SUPERSEDED")
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM retrieval_relation_embeddings"), 0)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM place_active_chunks"), 0)

    async def test_subject_queries_ignore_relation_vectors_even_when_enabled(self) -> None:
        _, runtime = await self.indexed()
        landscape = await runtime._retrieve_candidates({"filters": {"observation": {"content_kinds": ["landscape"]}}}, VECTOR)
        self.assertEqual([row["place_id"] for row in landscape], [394])
        self.assertAlmostEqual(landscape[0]["semantic_score"], 0.0)
        self.assertNotIn("retrieval_path", landscape[0]["evidence"])
        runtime.use_relation_vectors = False
        move = await runtime._retrieve_candidates({"filters": {"observation": {"destination_place_id": 395}}}, VECTOR)
        self.assertAlmostEqual(move[0]["semantic_score"], 0.0)
        self.assertNotIn("retrieval_path", move[0]["evidence"])


if __name__ == "__main__":
    unittest.main()
