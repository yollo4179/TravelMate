"""근거가 늘어도 장소 중복·합산 편향·귀속 손실이 생기지 않는지 검증한다."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contextual.ranking import EvidenceCount, build_pairs, rank_places, validate_token_budget


def document(identifier: str) -> dict:
    return {'chunk_id': identifier, 'context_version': 'v1', 'context_text': '방문 문맥',
            'chunk_text': identifier, 'source_id': identifier, 'source_version': 'source-v1',
            'source_span': {'start': 0, 'end': len(identifier)},
            'place_refs': [{'place_id': 1, 'role': 'subject'}]}


def candidate(place_id: int, evidence: dict | None = None) -> dict:
    return {'place_id': place_id, 'source_version': 1, 'evidence': evidence,
            'description': '일반 장소 설명', 'name': '장소', 'semantic_score': 0.9}


def row(place_id: int, evidence: dict | None, score: float = 0.9) -> dict:
    return {'place_id': place_id, 'source_version': 1, 'evidence': evidence, 'semantic_score': score}


class RankingTests(unittest.TestCase):
    def test_secondary_evidence_can_win_without_duplicating_place(self) -> None:
        primary, relevant = document('primary'), document('relevant')
        candidates = [candidate(1, primary), candidate(2)]
        rows = [row(1, primary), row(1, relevant, 0.8), row(2, None)]
        pairs = build_pairs(candidates, rows, EvidenceCount.TWO)
        ranked = rank_places(candidates, pairs, [0.1, 0.95, 0.7])
        self.assertEqual([place['place_id'] for place, _ in ranked], [1, 2])
        winner, score = ranked[0]
        self.assertEqual(score, 0.95)
        self.assertEqual(winner['evidence']['chunk_id'], 'relevant')
        self.assertEqual(winner['description'], pairs[1].text)
        self.assertEqual(winner['reranked_evidence_chunks'][0]['source_span'], relevant['source_span'])
        self.assertEqual(winner['reranked_evidence_chunks'][0]['semantic_score'], 0.8)
        self.assertNotIn('rerank_score', relevant)

    def test_many_weak_evidences_do_not_outscore_one_strong_evidence_by_sum(self) -> None:
        docs = [document(str(index)) for index in range(3)]
        candidates = [candidate(1, docs[0]), candidate(2)]
        pairs = build_pairs(candidates, [*(row(1, doc) for doc in docs), row(2, None)], EvidenceCount.THREE)
        ranked = rank_places(candidates, pairs, [0.4, 0.4, 0.4, 0.6])
        self.assertEqual([place['place_id'] for place, _ in ranked], [2, 1])

    def test_default_one_preserves_original_reranker_input(self) -> None:
        doc = document('primary')
        candidates = [candidate(1, json.dumps(doc)), candidate(2)]
        pairs = build_pairs(candidates, [], EvidenceCount.ONE)
        self.assertEqual([pair.text for pair in pairs], ['방문 문맥\n\nprimary', '일반 장소 설명'])

    def test_duplicate_context_does_not_consume_pair_slot(self) -> None:
        doc = document('primary')
        pairs = build_pairs([candidate(1, doc)], [row(1, doc), row(1, deepcopy(doc)), row(1, document('second'))], EvidenceCount.TWO)
        self.assertEqual(len(pairs), 2)

    def test_missing_or_changed_candidate_is_rejected(self) -> None:
        doc = document('primary')
        for rows in ([], [{**row(1, doc), 'source_version': 2}], [row(1, document('changed'))]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                build_pairs([candidate(1, doc)], rows, EvidenceCount.TWO)

    def test_empty_candidate_set_and_stable_ties(self) -> None:
        self.assertEqual(build_pairs([], [], EvidenceCount.TWO), [])
        candidates = [candidate(2), candidate(1)]
        pairs = build_pairs(candidates, [], EvidenceCount.ONE)
        self.assertEqual([place['place_id'] for place, _ in rank_places(candidates, pairs, [0.5, 0.5])], [2, 1])

    def test_invalid_count_and_nonfinite_or_missing_scores_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceCount(4)
        candidates = [candidate(1)]
        pairs = build_pairs(candidates, [], EvidenceCount.ONE)
        for scores in ([], [float('nan')], [float('inf')]):
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                rank_places(candidates, pairs, scores)

    def test_pair_budget_is_enforced_before_model_call(self) -> None:
        with self.assertRaisesRegex(ValueError, '예산'):
            build_pairs([candidate(index) for index in range(91)], [], EvidenceCount.ONE)

    def test_long_inputs_exceed_token_budget_even_with_few_pairs(self) -> None:
        pairs = build_pairs([candidate(index) for index in range(5)], [], EvidenceCount.ONE)
        validate_token_budget(pairs, [100] * 5)
        for lengths in ([8192] * 5, [100], [0] * 5):
            with self.subTest(lengths=lengths), self.assertRaises(ValueError):
                validate_token_budget(pairs, lengths)


if __name__ == '__main__':
    unittest.main()
