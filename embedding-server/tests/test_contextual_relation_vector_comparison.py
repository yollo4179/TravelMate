"""같은 질의·원문 점수는 재사용하고 누락된 리랭킹만 호출하는지 검증한다."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from Evaluation.tracks.contextual.relation_vector_comparison import rerank_missing, saved_score_cache


class RelationComparisonTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_exact_query_text_scores_without_http(self) -> None:
        def forbidden(_: httpx.Request) -> httpx.Response:
            raise AssertionError("이미 보존한 점수의 중복 호출 금지")
        cache = {("질문", "이동 근거"): 0.9}
        calls = []
        async with httpx.AsyncClient(base_url="http://localhost", transport=httpx.MockTransport(forbidden)) as client:
            values = await rerank_missing(client, "질문", ["이동 근거", "이동 근거"], cache, calls)
        self.assertEqual(values, [0.9, 0.9])
        self.assertEqual(calls, [])

    async def test_requests_only_missing_unique_text_and_preserves_pair_order(self) -> None:
        requests = []
        def send(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"scores": [0.8]})
        cache = {("질문", "보존 근거"): 0.7}
        calls = []
        async with httpx.AsyncClient(base_url="http://localhost", transport=httpx.MockTransport(send)) as client:
            values = await rerank_missing(client, "질문", ["보존 근거", "새 근거", "새 근거"], cache, calls)
        self.assertEqual(values, [0.7, 0.8, 0.8])
        self.assertEqual(requests, [{"query": "질문", "texts": ["새 근거"]}])
        self.assertEqual(len(calls), 1)

    async def test_wrong_count_and_nonfinite_scores_are_not_cached(self) -> None:
        for scores in ([], [float("nan")], [float("inf")]):
            cache = {}
            async with httpx.AsyncClient(base_url="http://localhost", transport=httpx.MockTransport(
                lambda _, scores=scores: httpx.Response(200, content=json.dumps({"scores": scores}).encode("utf-8"), headers={"content-type": "application/json"}))) as client:
                with self.assertRaises(ValueError):
                    await rerank_missing(client, "질문", ["이동 근거"], cache, [])
            self.assertEqual(cache, {})

    def test_saved_scores_are_keyed_by_query_and_full_reranking_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "search-summary.json").write_text(json.dumps({"results": [{"id": "q1", "ranked_places": [
                {"text": "출발지 A → B\n도보 이동", "score": 0.91}]}]}, ensure_ascii=False), encoding="utf-8")
            cache = saved_score_cache(root, [{"id": "q1", "query": "어디로 걷나"}])
            self.assertEqual(cache[("어디로 걷나", "출발지 A → B\n도보 이동")], 0.91)
            self.assertNotIn(("다른 질문", "출발지 A → B\n도보 이동"), cache)


if __name__ == "__main__":
    unittest.main()
