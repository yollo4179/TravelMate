"""일반 의미 검색의 관계 귀속과 표현별 근거 예산을 검사한다."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from typing import Any
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from app.contextual.observation_search import ObservationFilter
from app.contextual.ranking import EvidenceCount, build_pairs, rank_places
from app.contextual.retrieval import (
    RETRIEVAL_STRATEGIES,
    SemanticRelationRetrievalStrategy,
    resolve_retrieval_strategy,
)
from test_contextual_supporting_relations import QUOTE, fixture, parsed


class GeneralRelationTests(unittest.TestCase):
    def evidence(self) -> dict[str, Any]:
        bundle, raw = fixture()
        chunk, = parsed(bundle, raw)
        return {**chunk.to_dict(), "context_version": chunk.context_version}

    def test_registry_selects_exactly_one_strategy_with_optional_endpoints(self) -> None:
        conditions = (
            None,
            {"content_kinds": ["movement"]},
            {"origin_place_id": 394},
            {"destination_place_id": 395},
            {"content_kinds": ["landscape"]},
        )
        for enabled in (False, True):
            for condition in conditions:
                observation = ObservationFilter.from_mapping(condition)
                with self.subTest(enabled=enabled, condition=condition):
                    selected = resolve_retrieval_strategy(observation, enabled)
                    self.assertEqual(
                        sum(strategy.is_applicable(observation, enabled) for strategy in RETRIEVAL_STRATEGIES),
                        1,
                    )
                    self.assertEqual(isinstance(selected, SemanticRelationRetrievalStrategy), enabled and condition is None)
        with self.assertRaises(ValueError):
            resolve_retrieval_strategy(None, True, ())
        with self.assertRaises(ValueError):
            resolve_retrieval_strategy(None, True, RETRIEVAL_STRATEGIES * 2)

    def test_unfiltered_relation_preserves_direction_and_excludes_scenery_from_input(self) -> None:
        evidence = self.evidence()
        before = deepcopy(evidence)
        relation = {**evidence, "retrieval_path": "relation", "retrieved_relation_index": 0}
        strategy = resolve_retrieval_strategy(None, True)
        for place_id in (394, 395):
            scoped, = strategy.scope_rows([{"place_id": place_id, "evidence": relation}], None)
            self.assertIn("출발지: A공원 → 도착지: B공원", scoped["description"])
            self.assertIn(QUOTE, scoped["description"])
            self.assertNotIn("야경", scoped["description"])
            self.assertEqual(scoped["evidence"]["place_refs"], before["place_refs"])
            self.assertEqual(scoped["evidence"]["chunk_text"], before["chunk_text"])
        self.assertEqual(evidence, before)
        with self.assertRaises(ValueError):
            strategy.scope_rows([{"place_id": 999, "evidence": relation}], None)

    def test_chunk_and_relation_from_same_source_use_separate_evidence_slots(self) -> None:
        document = self.evidence()
        whole = {**document, "retrieval_path": "chunk"}
        relation = {**document, "retrieval_path": "relation", "retrieved_relation_index": 0}
        candidates = [{"place_id": 394, "source_version": 1, "semantic_score": 0.9, "evidence": whole}]
        rows = [
            {"place_id": 394, "source_version": 1, "semantic_score": score, "evidence": evidence}
            for score, evidence in ((0.9, whole), (0.8, relation))
        ]
        strategy = resolve_retrieval_strategy(None, True)
        expanded = strategy.scope_rows(rows, None)
        pairs = build_pairs(candidates, expanded, EvidenceCount.TWO)
        self.assertEqual(len(pairs), 2)
        self.assertIn("야경", pairs[0].text)
        self.assertNotIn("야경", pairs[1].text)
        ranked = rank_places(candidates, pairs, [0.7, 0.8])
        winner, score = ranked[0]
        self.assertEqual(score, 0.8)
        self.assertEqual(len(winner["reranked_evidence_chunks"]), 2)
        self.assertEqual(len(build_pairs(candidates, [], EvidenceCount.ONE)), 1)

    def test_duplicate_representation_is_removed_but_distinct_relations_are_kept(self) -> None:
        document = self.evidence()
        relation = {**document, "retrieval_path": "relation", "retrieved_relation_index": 0, "search_text": QUOTE}
        second = {**relation, "retrieved_relation_index": 1}
        candidates = [{"place_id": 394, "source_version": 1, "semantic_score": 0.9, "evidence": relation}]
        rows = [
            {"place_id": 394, "source_version": 1, "semantic_score": 0.9, "evidence": evidence}
            for evidence in (relation, deepcopy(relation), second)
        ]
        pairs = build_pairs(candidates, rows, EvidenceCount.TWO)
        self.assertEqual([pair.evidence["retrieved_relation_index"] for pair in pairs], [0, 1])

    def test_changed_representation_of_same_chunk_is_detected_before_reranking(self) -> None:
        document = self.evidence()
        primary = {**document, "retrieval_path": "relation", "retrieved_relation_index": 0}
        candidates = [{"place_id": 394, "source_version": 1, "semantic_score": 0.9, "evidence": primary}]
        for changed in ({**document, "retrieval_path": "chunk"}, {**primary, "retrieved_relation_index": 1}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "활성 근거"):
                build_pairs(
                    candidates,
                    [{"place_id": 394, "source_version": 1, "semantic_score": 0.9, "evidence": changed}],
                    EvidenceCount.TWO,
                )


if __name__ == "__main__":
    unittest.main()
