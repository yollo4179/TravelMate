"""일반·복합 질문이 이동 전용 정책으로 보류되거나 덮어써지지 않는지 검사한다."""
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
from app.contextual.contracts import ContentKind
from app.contextual.observation_search import ObservationFilter
from app.contextual.ranking import EvidenceCount, build_pairs, rank_places, validate_token_budget
from app.contextual.result_mapping import result_item
from app.contextual.relations import RelationImportance
from contextual_search_fixtures import BLOCK, WALK, candidate, document


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
    enums = [deepcopy(node) for node in syntax.body if isinstance(node, ast.ClassDef)
             and node.name in ("RankingMode", "EvidenceAssessmentStatus")]
    model = MagicMock(device="mock-only", model_name="mock-only", batch_size=8, execution_mode="mock-only")
    model.rerank.return_value = scores
    model.input_token_lengths.side_effect = lambda query, texts: [10] * len(texts)
    embedder = MagicMock(device="mock-only")
    embedder.embed.return_value = [[1.0] + [0.0] * 1023]
    embedder.getDimension.return_value = 1024
    namespace = {
        "Any": Any, "StrEnum": StrEnum, "json": json, "time": time, "uuid": uuid, "datetime": datetime, "UTC": UTC,
        "EvidenceCount": EvidenceCount, "ObservationFilter": ObservationFilter,
        "build_pairs": build_pairs, "rank_places": rank_places, "validate_token_budget": validate_token_budget,
        "RETRIEVE_TOP_K": 30, "TraceContextTextMapPropagator": MagicMock(), "tracer": MagicMock(),
        "embedder": embedder, "reranker": model, "to_thread": SimpleNamespace(run_sync=inline), "result_item": result_item,
    }
    exec(compile(ast.Module(body=[*enums, *methods], type_ignores=[]), "<general-search-contract>", "exec"), namespace)
    records = []
    candidates = deepcopy(candidates)
    for entry in candidates:
        documents = entry.pop("reranked_evidence_chunks", [])
        records.extend({"place_id": entry["place_id"], "source_version": entry["source_version"],
                        "evidence": evidence, "semantic_score": evidence["semantic_score"]} for evidence in documents)
        for key in ("region", "city", "category", "source_category", "latitude", "longitude", "tour_content_id", "image_url", "homepage_url"):
            entry[key] = None
        entry.update(name="검사 공원", latest_seen_version=entry["source_version"])
    runtime = SimpleNamespace(
        evidence_count=count,
        _retrieve_candidates=AsyncMock(return_value=candidates),
        _retrieve_evidence=AsyncMock(return_value=records),
        _retrieve_quality_context=AsyncMock(side_effect=AssertionError("일반 검색은 실험용 이동 정책을 조회하지 않는다")),
        _save_recommendation_result=AsyncMock(),
        _to_result_item=namespace["_to_result_item"],
    )
    runtime._complete_recommendation = MethodType(namespace["_complete_recommendation"], runtime)
    return runtime, model


def request_for(
    query: str,
    *,
    semantic_only: bool = False,
    limit: int = 20,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {"request_id": uuid.uuid4(), "created_at": now, "context_version": 1, "payload": json.dumps({
        "query": query, "ranking_mode": "SEMANTIC_ONLY" if semantic_only else "RERANKED",
        "requested_at": now.isoformat(), "limit": limit, "filters": filters or {},
    })}


class GeneralSearchContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_wifi_connection_is_not_withheld_in_either_ranking_mode(self) -> None:
        wifi = document("와이파이 연결이 안정적이고 콘센트가 있다.", relation=False, kind=ContentKind.FACILITY)
        for semantic_only in (False, True):
            for query in ("와이파이 연결이 잘되는 곳", "인터넷 연결 가능한 곳"):
                with self.subTest(query=query, semantic_only=semantic_only):
                    runtime, model = runtime_for([candidate(901, [wifi], [0.8])], [0.8])
                    await runtime._complete_recommendation(request_for(query, semantic_only=semantic_only))
                    result = runtime._save_recommendation_result.await_args.args[1]
                    self.assertEqual(result["returned_count"], 1)
                    self.assertEqual(result["items"][0]["description"], wifi["chunk_text"])
                    self.assertEqual(result["items"][0]["evidence_assessment"], {"status": "not_assessed"})
                    self.assertNotIn("withheld_results", result)
                    self.assertEqual(result["warnings"], [])
                    runtime._retrieve_quality_context.assert_not_called()
                    runtime._retrieve_evidence.assert_not_called()
                    if semantic_only:
                        model.rerank.assert_not_called()

    async def test_negative_conditional_and_positive_phrases_are_never_confirmed_as_success(self) -> None:
        quotes = (
            "도착공원까지 걸어갈 수 없다.",
            "도착공원까지 걸어갈 수 있다는 말은 사실이 아니다.",
            "공사가 끝나면 도착공원까지 걸어갈 수 있다.",
            WALK,
        )
        for quote in quotes:
            with self.subTest(quote=quote):
                original = document(quote)
                runtime, _ = runtime_for([candidate(901, [original], [0.9])], [0.9])
                await runtime._complete_recommendation(request_for("주변 관광지와 연결된 곳"))
                item, = runtime._save_recommendation_result.await_args.args[1]["items"]
                self.assertEqual(item["description"], quote)
                self.assertEqual(item["evidence_assessment"], {"status": "not_assessed"})
                self.assertEqual(item["evidence_chunks"], [original])

    async def test_scenery_relation_and_blocked_record_survive_without_description_overwrite(self) -> None:
        combined = document(
            "출발공원에서 야경을 감상했다. " + WALK,
            movement_quote=WALK,
            kind=ContentKind.LANDSCAPE,
            importance=RelationImportance.SUPPORTING,
            conditions=("계단을 내려가",),
        )
        blocked = document(BLOCK, conditions=("공사로 길이 막혀",))
        query = "야경 보고 다른 관광지까지 걸어갈 수 있는 곳"
        runtime, model = runtime_for(
            [candidate(901, [combined, blocked], [0.9, 0.2])],
            [0.9, 0.2],
            count=EvidenceCount.TWO,
        )
        await runtime._complete_recommendation(request_for(query))
        item, = runtime._save_recommendation_result.await_args.args[1]["items"]
        self.assertIn("야경", item["description"])
        self.assertIn(WALK, item["description"])
        self.assertEqual(len(item["evidence_chunks"]), 2)
        for original, returned in zip((combined, blocked), item["evidence_chunks"], strict=True):
            for key in original:
                self.assertEqual(returned[key], original[key], key)
        self.assertEqual(model.rerank.call_args.args[0], query)
        self.assertIn("야경", model.rerank.call_args.args[1][0])
        self.assertIn(BLOCK, model.rerank.call_args.args[1][1])
        self.assertEqual(item["evidence_assessment"], {"status": "not_assessed"})
        runtime._retrieve_quality_context.assert_not_called()

    async def test_blocked_representative_is_not_silently_replaced_and_remains_unassessed(self) -> None:
        blocked, positive = document(BLOCK), document(WALK)
        runtime, _ = runtime_for(
            [candidate(902, [blocked, positive], [0.9, 0.1])],
            [0.9, 0.1],
            count=EvidenceCount.TWO,
        )
        await runtime._complete_recommendation(request_for("주변 관광지와 연결된 곳"))
        item, = runtime._save_recommendation_result.await_args.args[1]["items"]
        self.assertIn(BLOCK, item["description"])
        self.assertEqual(item["evidence_chunks"][0]["chunk_id"], blocked["chunk_id"])
        self.assertEqual(item["evidence_chunks"][1]["chunk_id"], positive["chunk_id"])
        self.assertEqual(item["evidence_assessment"], {"status": "not_assessed"})

    async def test_separate_scenery_and_relation_evidence_are_returned_together(self) -> None:
        scenery = document("출발공원의 야경이 아름답다.", relation=False, kind=ContentKind.LANDSCAPE)
        movement = document(WALK, conditions=("계단을 내려가",))
        runtime, _ = runtime_for(
            [candidate(901, [scenery, movement], [0.9, 0.7])],
            [0.9, 0.7],
            count=EvidenceCount.TWO,
        )
        await runtime._complete_recommendation(request_for("야경 보고 다른 관광지까지 걸어갈 수 있는 곳"))
        item, = runtime._save_recommendation_result.await_args.args[1]["items"]
        observation, relation = item["evidence_chunks"]
        self.assertIn(scenery["chunk_text"], item["description"])
        self.assertEqual(observation["content_kind"], ContentKind.LANDSCAPE)
        self.assertEqual(observation["place_refs"], scenery["place_refs"])
        self.assertEqual(relation["relations"], movement["relations"])
        self.assertEqual(relation["chunk_text"], WALK)
        self.assertEqual(item["evidence_assessment"], {"status": "not_assessed"})

    async def test_original_order_and_limit_are_preserved_without_semantic_withholding(self) -> None:
        first = document("흙길이 보인다.", relation=False)
        second = document(WALK)
        runtime, _ = runtime_for(
            [candidate(901, [first], [0.9]), candidate(902, [second], [0.01])],
            [0.9, 0.01],
        )
        await runtime._complete_recommendation(request_for("주변 관광지와 연결된 곳", limit=1))
        result = runtime._save_recommendation_result.await_args.args[1]
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["items"][0]["place_id"], 901)
        self.assertEqual(result["items"][0]["rerank_score"], 0.9)
        self.assertNotIn("withheld_count", result)

    async def test_explicit_movement_filters_are_forwarded_without_natural_language_override(self) -> None:
        original = document(WALK)
        filters = {"observation": {"content_kinds": [ContentKind.MOVEMENT], "origin_place_id": 901}}
        runtime, _ = runtime_for([candidate(901, [original], [0.3])], [0.3])
        await runtime._complete_recommendation(request_for("다른 곳으로 이동", filters=filters))
        result = runtime._save_recommendation_result.await_args.args[1]
        self.assertEqual(result["applied_filters"], filters)
        self.assertEqual(runtime._retrieve_candidates.await_args.args[0]["filters"], filters)
        self.assertEqual(result["returned_count"], 1)
        runtime._retrieve_quality_context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
