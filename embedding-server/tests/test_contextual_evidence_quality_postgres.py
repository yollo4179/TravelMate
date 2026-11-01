"""벡터 재검색 없이 활성 관계 문맥과 변경된 스냅샷을 검사한다."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from app.contextual.evidence_quality import ContextCoverage
import test_contextual_relation_vectors_postgres as relations


@unittest.skipUnless(os.environ.get("CONTEXTUAL_ISOLATED_DATABASE") == "1", "폐기용 DB를 명시해야 실행")
class QualityContextPostgresTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = relations.RelationVectorPostgresTests.asyncSetUp
    asyncTearDown = relations.RelationVectorPostgresTests.asyncTearDown
    prepared = relations.RelationVectorPostgresTests.prepared
    runtime = relations.RelationVectorPostgresTests.runtime
    indexed = relations.RelationVectorPostgresTests.indexed

    async def test_active_context_contains_original_quote_and_endpoint_without_vector_search(self) -> None:
        chunks, runtime = await self.indexed()
        candidate = {"place_id": 395, "source_version": 1, "evidence": {**chunks[0].to_dict(), "context_version": chunks[0].context_version}}
        contexts = await runtime._retrieve_quality_context([(candidate, 0.9)])
        context = contexts[395]
        self.assertEqual(context.coverage, ContextCoverage.ACTIVE)
        self.assertEqual(len(context.documents), 1)
        self.assertEqual(context.documents[0]["relations"], chunks[0].relations)
        self.assertEqual(context.documents[0]["place_refs"], chunks[0].place_refs)

    async def test_removed_active_link_and_changed_source_are_not_treated_as_current(self) -> None:
        chunks, runtime = await self.indexed()
        candidate = {"place_id": 395, "source_version": 1, "evidence": {**chunks[0].to_dict(), "context_version": chunks[0].context_version}}
        await self.pool.execute("DELETE FROM place_active_chunks WHERE place_id=395")
        contexts = await runtime._retrieve_quality_context([(candidate, 0.9)])
        self.assertEqual(contexts[395].coverage, ContextCoverage.CHANGED)
        await self.pool.execute("UPDATE place_embeddings SET latest_seen_version=2 WHERE place_id=394")
        candidate["place_id"] = 394
        contexts = await runtime._retrieve_quality_context([(candidate, 0.9)])
        self.assertEqual(contexts[394].coverage, ContextCoverage.CHANGED)


if __name__ == "__main__":
    unittest.main()
