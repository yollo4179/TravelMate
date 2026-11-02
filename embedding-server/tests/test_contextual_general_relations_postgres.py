"""일반 검색의 관계 후보·선택 필터·귀속을 폐기용 PostgreSQL에서 검증한다."""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from app.contextual.observation_search import ObservationFilter
from app.contextual.pipeline import normalize_source
from app.contextual.ranking import EvidenceCount, build_pairs
from app.contextual.repository import activate_chunks, store_relation_embeddings
from app.contextual.relation_vectors import relation_embedding_inputs
import test_contextual_relation_vectors_postgres as relations


@unittest.skipUnless(os.environ.get("CONTEXTUAL_ISOLATED_DATABASE") == "1", "폐기용 DB를 명시해야 실행")
class GeneralRelationPostgresTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = relations.RelationVectorPostgresTests.asyncSetUp
    asyncTearDown = relations.RelationVectorPostgresTests.asyncTearDown
    prepared = relations.RelationVectorPostgresTests.prepared
    runtime = relations.RelationVectorPostgresTests.runtime
    indexed = relations.RelationVectorPostgresTests.indexed

    async def test_no_observation_or_endpoint_searches_relation_vectors_and_scopes_both_ends(self) -> None:
        chunks, runtime = await self.indexed()
        candidates = await runtime._retrieve_candidates({"filters": {}}, relations.VECTOR)
        self.assertEqual([row["place_id"] for row in candidates], [394, 395])
        for row in candidates:
            self.assertAlmostEqual(row["semantic_score"], 1.0)
            self.assertEqual(row["evidence"]["retrieval_path"], "relation")
            self.assertIn(chunks[0].relations[0]["evidence"]["quote"], row["description"])
            self.assertNotIn("야경", row["description"])
        expanded = await runtime._retrieve_evidence(candidates, relations.VECTOR, EvidenceCount.TWO)
        pairs = build_pairs(candidates, expanded, EvidenceCount.TWO)
        a_pairs = [pair for pair in pairs if candidates[pair.candidate_index]["place_id"] == 394]
        b_pairs = [pair for pair in pairs if candidates[pair.candidate_index]["place_id"] == 395]
        self.assertEqual(len(a_pairs), 2)
        self.assertEqual(len(b_pairs), 1)
        self.assertTrue(any("야경" in pair.text for pair in a_pairs))
        self.assertTrue(all("야경" not in pair.text for pair in b_pairs))

    async def test_strong_scenery_vector_never_becomes_destinations_scenery_evidence(self) -> None:
        chunks, runtime = await self.indexed()
        async with self.pool.acquire() as connection:
            for place_id in (394, 395):
                await activate_chunks(connection, place_id, chunks, [relations.V])
            await store_relation_embeddings(connection, relation_embedding_inputs(chunks), [relations.OTHER])
        candidates = await runtime._retrieve_candidates({"filters": {}}, relations.VECTOR)
        origin, destination = candidates
        self.assertEqual(origin["place_id"], 394)
        self.assertAlmostEqual(origin["semantic_score"], 1.0)
        self.assertIn("야경", origin["description"])
        self.assertEqual(destination["place_id"], 395)
        self.assertAlmostEqual(destination["semantic_score"], 0.0)
        self.assertNotIn("야경", destination["description"])

    async def test_endpoint_free_movement_and_origin_only_conditions_remain_optional(self) -> None:
        _, runtime = await self.indexed()
        cases = (
            ({"content_kinds": ["movement"]}, [394, 395]),
            ({"origin_place_id": 394}, [395]),
            ({"destination_place_id": 395}, [394]),
        )
        for condition, expected in cases:
            with self.subTest(condition=condition):
                candidates = await runtime._retrieve_candidates({"filters": {"observation": condition}}, relations.VECTOR)
                self.assertEqual([row["place_id"] for row in candidates], expected)
                expanded = await runtime._retrieve_evidence(
                    candidates,
                    relations.VECTOR,
                    EvidenceCount.TWO,
                    observation=ObservationFilter.from_mapping(condition),
                )
                self.assertTrue(all("야경" not in pair.text for pair in build_pairs(candidates, expanded, EvidenceCount.TWO)))

    async def test_general_relation_candidates_respect_existing_place_filters(self) -> None:
        _, runtime = await self.indexed()
        await self.pool.execute("UPDATE place_embeddings SET region='서울',city='강남구',category='공원',latitude=37.5,longitude=127.0")
        filters = {
            "region": "서울",
            "city": "강남구",
            "category": "공원",
            "exclude_place_ids": [395],
            "area": {"center": {"lat": 37.5, "lon": 127.0}, "radius_meters": 100},
        }
        candidates = await runtime._retrieve_candidates({"filters": filters}, relations.VECTOR)
        self.assertEqual([row["place_id"] for row in candidates], [394])
        for name, value in (("city", "서초구"), ("region", "부산"), ("category", "카페")):
            with self.subTest(name=name):
                self.assertEqual(await runtime._retrieve_candidates({"filters": {**filters, name: value}}, relations.VECTOR), [])
        self.assertEqual(await runtime._retrieve_candidates({"filters": {**filters, "area": {"center": {"lat": 35.0, "lon": 129.0}, "radius_meters": 100}}}, relations.VECTOR), [])

    async def test_inactive_and_stale_endpoints_are_not_reintroduced_in_general_search(self) -> None:
        _, runtime = await self.indexed()
        await self.pool.execute("DELETE FROM place_active_chunks WHERE place_id=395")
        candidates = await runtime._retrieve_candidates({"filters": {}}, relations.VECTOR)
        self.assertEqual([row["place_id"] for row in candidates], [394])
        await self.pool.execute("UPDATE place_embeddings SET latest_seen_version=2 WHERE place_id=394")
        self.assertEqual(await runtime._retrieve_candidates({"filters": {}}, relations.VECTOR), [])

    async def test_disabled_mode_keeps_subject_search_and_tied_representations_are_stable(self) -> None:
        chunks, runtime = await self.indexed()
        runtime.use_relation_vectors = False
        candidates = await runtime._retrieve_candidates({"filters": {}}, relations.VECTOR)
        self.assertEqual([row["place_id"] for row in candidates], [394])
        self.assertAlmostEqual(candidates[0]["semantic_score"], 0.0)
        runtime.use_relation_vectors = True
        async with self.pool.acquire() as connection:
            await activate_chunks(connection, 394, chunks, [relations.V])
        candidates = await runtime._retrieve_candidates({"filters": {}}, relations.VECTOR)
        self.assertEqual(candidates[0]["evidence"]["retrieval_path"], "chunk")
        expanded = await runtime._retrieve_evidence(candidates, relations.VECTOR, EvidenceCount.TWO)
        pairs = build_pairs(candidates, expanded, EvidenceCount.TWO)
        self.assertEqual(len(pairs), 3)

    async def test_general_search_keeps_top_thirty_places_without_summing_representations(self) -> None:
        _, runtime = await self.indexed()
        await self.pool.execute(
            "INSERT INTO place_embeddings(place_id,source_version,latest_seen_version,name,embedding) "
            "SELECT identifier,1,1,'방해 장소 '||identifier,$1::vector FROM generate_series(1000,1039) identifier",
            relations.VECTOR,
        )
        candidates = await runtime._retrieve_candidates({"filters": {}}, relations.VECTOR)
        identifiers = [row["place_id"] for row in candidates]
        self.assertEqual(len(identifiers), 30)
        self.assertEqual(len(set(identifiers)), 30)
        self.assertEqual(identifiers[:2], [394, 395])
        self.assertTrue(all(row["semantic_score"] <= 1.0 for row in candidates))
        self.assertLessEqual(await self.pool.fetchval("SELECT max(slot) FROM place_active_chunks"), 20)

    async def test_two_relations_of_same_chunk_remain_distinct_within_evidence_budget(self) -> None:
        chunks, runtime = await self.indexed()
        await self.pool.execute("INSERT INTO place_embeddings(place_id,source_version,latest_seen_version,name) VALUES(396,1,1,'C공원')")
        quotes = ("관람 후 B공원으로 걸어갈 수 있다.", "C공원까지 버스로 갈 수 있다.")
        text = "A공원은 야경이 아름답고, " + " ".join(quotes)
        source = normalize_source({
            "source_type": "review",
            "title": "서로 다른 목적지와 교통수단",
            "text": text,
            "metadata": {"source_url": "https://example.org/general-two-routes", "capture_scope": "full_text"},
        })
        edges = [
            {
                "type": "movement",
                "importance": "supporting",
                "origin": {"place_id": 394, "name": "A공원"},
                "destination": {"place_id": place_id, "name": name},
                "conditions": [],
                "evidence": {"start": text.index(quote), "end": text.index(quote) + len(quote), "quote": quote},
            }
            for place_id, name, quote in ((395, "B공원", quotes[0]), (396, "C공원", quotes[1]))
        ]
        chunk = replace(
            chunks[0],
            source=source,
            start=0,
            end=len(text),
            place_refs=chunks[0].place_refs + [{"place_id": 396, "role": "mentioned"}],
            relations=edges,
        )
        async with self.pool.acquire() as connection:
            await activate_chunks(connection, 394, [chunk], [relations.OTHER])
            await store_relation_embeddings(
                connection,
                relation_embedding_inputs([chunk]),
                [relations.V, [1.0, 1.0] + [0.0] * 1022],
            )
        candidates = await runtime._retrieve_candidates({"filters": {"exclude_place_ids": [395, 396]}}, relations.VECTOR)
        expanded = await runtime._retrieve_evidence(candidates, relations.VECTOR, EvidenceCount.TWO)
        pairs = build_pairs(candidates, expanded, EvidenceCount.TWO)
        self.assertEqual([pair.evidence["retrieved_relation_index"] for pair in pairs], [0, 1])
        for pair, quote in zip(pairs, quotes, strict=True):
            self.assertIn(quote, pair.text)
            self.assertNotIn("야경", pair.text)
        self.assertNotIn(quotes[1], pairs[0].text)
        self.assertNotIn(quotes[0], pairs[1].text)


if __name__ == "__main__":
    unittest.main()
