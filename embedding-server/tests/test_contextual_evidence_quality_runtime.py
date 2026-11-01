"""모델·검색 응답을 재사용해 실제 완료 이벤트의 보류·불확실성 경로를 검사한다."""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import UTC, datetime
from enum import StrEnum
import json
from pathlib import Path
import sys
import time
from types import MethodType, SimpleNamespace
from typing import Any, Callable
import unittest
from unittest.mock import AsyncMock, MagicMock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from app.contextual.evidence_quality import ContextCoverage, EvidenceContext, RequirementScope, apply_connection_quality, question_requirement
from app.contextual.observation_search import ObservationFilter
from app.contextual.ranking import EvidenceCount, build_pairs, rank_places, validate_token_budget
from test_contextual_evidence_quality import BLOCK, WALK, candidate, document


class RankingMode(StrEnum):
    RERANKED = "RERANKED"
    SEMANTIC_ONLY = "SEMANTIC_ONLY"


async def inline(function: Callable[[], Any]) -> Any:
    return function()


def runtime_for(
    candidates: list[dict[str, Any]],
    scores: list[float],
    *,
    count: EvidenceCount = EvidenceCount.ONE,
) -> tuple[Any, MagicMock]:
    syntax = ast.parse((ROOT / "app/kafka_runtime.py").read_text(encoding="utf-8"))
    runtime_class = next(node for node in syntax.body if isinstance(node, ast.ClassDef) and node.name == "KafkaRuntime")
    methods = [deepcopy(node) for node in runtime_class.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name in ("_complete_recommendation", "_to_result_item")]
    for method in methods:
        method.decorator_list = []
    model = MagicMock(device="mock-only", model_name="mock-only", batch_size=8, execution_mode="mock-only")
    model.rerank.return_value = scores
    model.input_token_lengths.side_effect = lambda query, texts: [10] * len(texts)
    embedder = MagicMock(device="mock-only")
    embedder.embed.return_value = [[1.0] + [0.0] * 1023]
    embedder.getDimension.return_value = 1024
    namespace = {
        "Any": Any, "json": json, "time": time, "uuid": uuid, "datetime": datetime, "UTC": UTC,
        "RankingMode": RankingMode, "EvidenceCount": EvidenceCount, "ObservationFilter": ObservationFilter,
        "build_pairs": build_pairs, "rank_places": rank_places, "validate_token_budget": validate_token_budget,
        "RequirementScope": RequirementScope, "question_requirement": question_requirement,
        "apply_connection_quality": apply_connection_quality, "RETRIEVE_TOP_K": 30,
        "TraceContextTextMapPropagator": MagicMock(), "tracer": MagicMock(),
        "embedder": embedder, "reranker": model, "to_thread": SimpleNamespace(run_sync=inline),
    }
    exec(compile(ast.Module(body=methods, type_ignores=[]), "<worker-quality>", "exec"), namespace)
    records = []
    contexts = {}
    for entry in candidates:
        documents = entry.pop("reranked_evidence_chunks", [])
        records.extend({"place_id": entry["place_id"], "source_version": entry["source_version"],
                        "evidence": evidence, "semantic_score": evidence["semantic_score"]} for evidence in documents)
        contexts[entry["place_id"]] = EvidenceContext(tuple(documents), ContextCoverage.ACTIVE)
        for key in ("region", "city", "category", "source_category", "latitude", "longitude", "tour_content_id", "image_url", "homepage_url"):
            entry[key] = None
        entry.update(name="검사 공원", latest_seen_version=entry["source_version"])
    runtime = SimpleNamespace(
        evidence_count=count,
        _retrieve_candidates=AsyncMock(return_value=candidates),
        _retrieve_evidence=AsyncMock(return_value=records),
        _retrieve_quality_context=AsyncMock(return_value=contexts),
        _save_recommendation_result=AsyncMock(),
        _to_result_item=namespace["_to_result_item"],
    )
    runtime._complete_recommendation = MethodType(namespace["_complete_recommendation"], runtime)
    return runtime, model


def request_for(
    query: str,
    *,
    mode: RankingMode = RankingMode.RERANKED,
    limit: int = 1,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {"request_id": uuid.uuid4(), "created_at": now, "context_version": 1, "payload": json.dumps({
        "query": query, "ranking_mode": mode, "requested_at": now.isoformat(), "limit": limit, "filters": {},
    })}


class QualityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_one_withholds_before_limit_and_persists_reason(self) -> None:
        unsupported = document("다른 관광지에 관한 설명이 없는 흙길이다.", relation=False)
        positive = document(WALK)
        runtime, _ = runtime_for([candidate(901, [unsupported], [0.9]), candidate(902, [positive], [0.01])], [0.9, 0.01])
        await runtime._complete_recommendation(request_for("주변 관광지와 연결된 곳"))
        result = runtime._save_recommendation_result.await_args.args[1]
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["items"][0]["place_id"], 902)
        self.assertEqual(result["items"][0]["rank"], 1)
        self.assertEqual(result["withheld_results"][0]["reason"], "no_verified_connection_evidence")
        self.assertTrue(result["warnings"])
        runtime._retrieve_evidence.assert_not_called()

    async def test_semantic_only_uses_same_policy_without_reranking(self) -> None:
        runtime, model = runtime_for([candidate(901, [document("흙길이 보인다.", relation=False)], [0.9])], [])
        await runtime._complete_recommendation(request_for("연결된 곳", mode=RankingMode.SEMANTIC_ONLY))
        result = runtime._save_recommendation_result.await_args.args[1]
        self.assertEqual(result["items"], [])
        self.assertEqual(result["withheld_count"], 1)
        self.assertEqual(result["status"], "COMPLETED")
        model.rerank.assert_not_called()

    async def test_two_evidence_mode_surfaces_conflict_and_original_ranking_score(self) -> None:
        blocked, positive = document(BLOCK), document(WALK)
        runtime, _ = runtime_for([candidate(902, [blocked, positive], [0.9, 0.1])], [0.9, 0.1], count=EvidenceCount.TWO)
        await runtime._complete_recommendation(request_for("주변 관광지와 연결된 곳"))
        result = runtime._save_recommendation_result.await_args.args[1]
        item, = result["items"]
        self.assertEqual(item["rerank_score"], 0.9)
        self.assertEqual(item["evidence_assessment"]["representative_rerank_score"], 0.1)
        self.assertEqual(item["evidence_assessment"]["status"], "conflicting_reports")
        self.assertIn(WALK, item["description"])
        self.assertIn(BLOCK, item["description"])
        self.assertEqual(len(item["evidence_chunks"]), 2)

    async def test_unrelated_question_preserves_results_and_skips_context_read(self) -> None:
        runtime, _ = runtime_for([candidate(901, [document("벤치가 있다.", relation=False)], [0.8])], [0.8])
        await runtime._complete_recommendation(request_for("벤치가 있는 공원"))
        result = runtime._save_recommendation_result.await_args.args[1]
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["evidence_quality_scope"], "not_assessed")
        self.assertNotIn("evidence_assessment", result["items"][0])
        runtime._retrieve_quality_context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
