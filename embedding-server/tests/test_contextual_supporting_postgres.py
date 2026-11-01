"""명시한 폐기용 PostgreSQL에서 역할·트리거·검색 SQL을 함께 검사한다."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse
from unittest.mock import patch
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.contextual.artifacts import collect_bundle, load_record
from app.contextual.contracts import SplitterVersion
from app.contextual.input_format import InputVersion
from app.contextual.observation_search import ObservationFilter
from app.contextual.pipeline import select_active
from app.contextual.prompts import PromptVersion
from app.contextual.ranking import EvidenceCount
from app.contextual.repository import activate_chunks, apply_bundle, desired_chunks, ensure_schema
from app.contextual.review import approval_document
import test_contextual_chunks as legacy_cases
from test_contextual_chunks import SETTINGS
from test_contextual_supporting_relations import A, B, TEXT, fixture, rows, changed


@unittest.skipUnless(os.environ.get("CONTEXTUAL_ISOLATED_DATABASE") == "1", "폐기용 DB를 명시해야 실행")
class SupportingPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        target = urlparse(os.environ["ENRICHMENT_TEST_DATABASE_URL"])
        if not target.hostname.startswith("tm-v7-eval-") or not target.path.startswith("/contextual_v7_eval"):
            raise ValueError("전용 컨테이너·DB 이름을 확인할 수 없습니다")
        await legacy_cases.ContextualDatabaseTests.asyncSetUp(self)
        for place in (A, B):
            await self.pool.execute("UPDATE place_embeddings SET name=$2,description=NULL WHERE place_id=$1", place.place_id, place.name)

    async def asyncTearDown(self) -> None:
        await legacy_cases.ContextualDatabaseTests.asyncTearDown(self)

    runtime = legacy_cases.ContextualDatabaseTests.runtime

    async def prepared(self, *, relation_only: bool = False) -> tuple[Path, Path, list]:
        value, raw = fixture()
        if relation_only:
            document = rows(raw)
            document["chunks"][0]["place_refs"][0]["role"] = "mentioned"
            raw = changed(raw, document)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,json=raw))) as client:
            path = await collect_bundle(value, SETTINGS, self.root / "records", client,
                prompt_version=PromptVersion.V7, input_version=InputVersion.EXPLICIT, splitter_version=SplitterVersion.SENTENCE)
        _, chunks, _ = load_record(path)
        approval = self.root / "approval.json"
        approval.write_text(json.dumps(approval_document(path,[chunk.chunk_id for chunk in chunks],"폐기용 DB 합성 검사")),encoding="utf-8")
        return path, approval, chunks

    async def activate(self, chunks: list) -> None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                for place in (A,B):
                    active = select_active(place.place_id,chunks)
                    await activate_chunks(connection,place.place_id,active,[[1.0]+[0.0]*1023 for _ in active])
        await self.pool.execute("UPDATE place_embeddings SET embedding=$1::vector", "["+",".join(["1"]+["0"]*1023)+"]")

    async def test_apply_roundtrip_uses_one_chunk_and_two_distinct_roles(self) -> None:
        path, approval, chunks = await self.prepared()
        self.assertEqual(await apply_bundle(self.pool,path,review_path=approval),"REINDEX_QUEUED")
        self.assertEqual(await apply_bundle(self.pool,path,review_path=approval),"ALREADY_APPLIED")
        for place in (A,B):
            generation, restored = await desired_chunks(self.pool,place)
            self.assertEqual(generation,1)
            self.assertEqual(restored[0].to_dict(),chunks[0].to_dict())
        await self.activate(chunks)
        result = await self.pool.fetch("SELECT place_id,role FROM place_active_chunks ORDER BY place_id")
        self.assertEqual([(row['place_id'],row['role']) for row in result],[(394,'subject'),(395,'relation_endpoint')])
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM retrieval_chunks"),1)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM retrieval_chunk_contexts"),1)

    async def test_trigger_rejects_destination_subject_unrelated_endpoint_and_invalid_role(self) -> None:
        import asyncpg
        _, _, chunks = await self.prepared()
        await self.activate(chunks)
        await self.pool.execute("INSERT INTO place_embeddings(place_id,source_version,latest_seen_version,name) VALUES(396,1,1,'C공원')")
        for place_id, role in ((395,'subject'),(396,'relation_endpoint'),(395,'unsupported')):
            async with self.pool.acquire() as connection:
                with self.assertRaises(asyncpg.CheckViolationError):
                    async with connection.transaction():
                        await connection.execute("DELETE FROM place_active_chunks WHERE place_id=$1",place_id)
                        await connection.execute("INSERT INTO place_active_chunks(place_id,slot,chunk_id,context_version,role) VALUES($1,1,$2,$3,$4)",
                            place_id,uuid.UUID(chunks[0].chunk_id),chunks[0].context_version,role)
        self.assertEqual(await self.pool.fetchval("SELECT role FROM place_active_chunks WHERE place_id=395"),'relation_endpoint')

    async def test_actual_direction_kind_and_importance_queries_and_evidence_expansion(self) -> None:
        _, _, chunks = await self.prepared()
        await self.activate(chunks)
        _, runtime, _ = self.runtime()
        vector = "["+",".join(["1"]+["0"]*1023)+"]"
        for condition, expected in (({'content_kinds':['landscape']},[394]),({'destination_place_id':395},[394]),
            ({'origin_place_id':394},[395]),({'relation_importance':['supporting']},[394,395]),({'relation_importance':['primary']},[])):
            with self.subTest(condition=condition):
                candidates = await runtime._retrieve_candidates({'filters':{'observation':condition}},vector)
                self.assertEqual([row['place_id'] for row in candidates],expected)
                if condition.get('content_kinds') != ['landscape']:
                    for row in candidates:
                        self.assertNotIn('야경',row['description'])
                expanded = await runtime._retrieve_evidence(candidates,vector,EvidenceCount.TWO,observation=ObservationFilter.from_mapping(condition))
                self.assertEqual([row['place_id'] for row in expanded],expected)
        ordinary = await runtime._retrieve_candidates({'filters':{}},vector)
        b = next(row for row in ordinary if row['place_id']==395)
        self.assertIsNone(b['evidence'])

    async def test_subject_only_constraint_migrates_without_deleting_existing_subject(self) -> None:
        _, _, chunks = await self.prepared()
        async with self.pool.acquire() as connection:
            await activate_chunks(connection,394,chunks,[[1.0]+[0.0]*1023])
        await self.pool.execute("ALTER TABLE place_active_chunks DROP CONSTRAINT place_active_chunks_role_check; "
                                "ALTER TABLE place_active_chunks ADD CONSTRAINT place_active_chunks_role_check CHECK(role='subject')")
        await ensure_schema(self.pool)
        await ensure_schema(self.pool)
        self.assertEqual(await self.pool.fetchval("SELECT role FROM place_active_chunks WHERE place_id=394"),'subject')
        await self.activate(chunks)
        self.assertEqual(await self.pool.fetchval("SELECT role FROM place_active_chunks WHERE place_id=395"),'relation_endpoint')

    async def test_relation_only_chunk_remains_direction_searchable_but_has_no_landscape_owner(self) -> None:
        _, _, chunks = await self.prepared(relation_only=True)
        await self.activate(chunks)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM place_active_chunks WHERE role='subject'"),0)
        _, runtime, _ = self.runtime()
        vector = "["+",".join(["1"]+["0"]*1023)+"]"
        self.assertEqual(await runtime._retrieve_candidates({'filters':{'observation':{'content_kinds':['landscape']}}},vector),[])
        result = await runtime._retrieve_candidates({'filters':{'observation':{'origin_place_id':394}}},vector)
        self.assertEqual([row['place_id'] for row in result],[395])

    async def test_stale_endpoint_aborts_apply_without_partial_subject_write(self) -> None:
        path, approval, _ = await self.prepared()
        await self.pool.execute("UPDATE place_embeddings SET latest_seen_version=2 WHERE place_id=395")
        with self.assertRaisesRegex(ValueError,'unavailable'):
            await apply_bundle(self.pool,path,review_path=approval)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM retrieval_chunk_bundles"),0)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM place_index_jobs"),0)


if __name__=='__main__':
    unittest.main()
