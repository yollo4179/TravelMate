"""Ranking metrics use the same graded human judgments for both strategies."""
from __future__ import annotations

import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_dataset
from evaluate_ranking import RANKING_VERSIONS, aggregate, evaluate, evaluate_case, score_order


class RankingMetricTests(unittest.TestCase):
    def test_top_k_accuracy_is_a_hit_not_the_recall_fraction(self) -> None:
        scores = score_order([99, 10, 98, 97, 96, 20, 30], {10: 3, 20: 2, 30: 3}, cutoff=5)

        self.assertEqual(scores['top_1_accuracy'], 0.0)
        self.assertEqual(scores['top_5_accuracy'], 1.0)
        self.assertAlmostEqual(scores['recall_at_5'], 1 / 3)
        self.assertEqual(scores['precision_at_5'], 0.2)

    def test_only_a_hit_after_position_five_changes_top_ten_accuracy(self) -> None:
        place_ids = [91, 92, 93, 94, 95, 10]
        judgments = {10: 3}

        self.assertEqual(score_order(place_ids, judgments, cutoff=5)['top_5_accuracy'], 0.0)
        self.assertEqual(score_order(place_ids, judgments, cutoff=10)['top_10_accuracy'], 1.0)

    def test_top_one_and_empty_response_have_explicit_binary_results(self) -> None:
        scores = score_order([10, 20], {10: 2, 20: 1}, cutoff=5)
        self.assertEqual(scores['top_1_accuracy'], 1.0)
        self.assertEqual(scores['top_5_accuracy'], 1.0)
        empty = score_order([], {10: 3}, cutoff=5)
        self.assertTrue(all(value == 0.0 for value in empty.values()))

    def test_unjudged_results_are_reported_without_being_declared_errors(self) -> None:
        case = {
            'case_id': 'fixture-case', 'query': '조건에 맞는 장소',
            'answerability': 'answerable', 'evaluation_track': 'search_api',
            'execution': {'status': 'completed', 'condition_coverage': 'complete'},
            'ranking_comparison': {
                version: {'place_ids': [99, 20], 'execution': {'status': 'completed'}}
                for version in RANKING_VERSIONS
            },
        }
        result = evaluate_case(case, {'fixture-case': {10: 3, 20: 0}}, cutoff=5)
        for version in RANKING_VERSIONS:
            coverage = result['judgment_coverage'][version]
            self.assertTrue(coverage['top_1_unjudged'])
            self.assertEqual(coverage['unjudged_place_ids_at_k'], [99])
            self.assertTrue(coverage['top_k_no_known_hit_with_unjudged_candidates'])
            self.assertEqual(coverage['judged_at_k'], 1)

    def test_averaging_binary_hits_produces_query_level_accuracy(self) -> None:
        orders = [[10], [90, 10], [90]]
        results = [
            {'ranking_versions': {version: score_order(order, {10: 3}, cutoff=5) for version in RANKING_VERSIONS}}
            for order in orders
        ]
        for scores in aggregate(results, cutoff=5).values():
            self.assertAlmostEqual(scores['top_1_accuracy'], 1 / 3)
            self.assertAlmostEqual(scores['top_5_accuracy'], 2 / 3)

    def test_invalid_cutoffs_are_rejected(self) -> None:
        for cutoff in (0, -1, True, 1.5):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                score_order([10], {10: 3}, cutoff=cutoff)

    def test_f1_and_map_use_binary_relevance_threshold_and_top_ten(self) -> None:
        scores = score_order(
            [50, 10, 20],
            {10: 3, 20: 2, 30: 1},
        )

        self.assertEqual(scores["precision_at_10"], 0.2)
        self.assertEqual(scores["recall_at_10"], 1.0)
        self.assertAlmostEqual(scores["f1_at_10"], 1 / 3)
        self.assertAlmostEqual(scores["map_at_10"], 7 / 12)

    def test_duplicate_retrieved_relevant_id_is_not_counted_twice(self) -> None:
        scores = score_order(
            [10, 10, 20],
            {10: 3, 20: 2},
        )

        self.assertAlmostEqual(scores["recall_at_10"], 1.0)
        self.assertAlmostEqual(scores["map_at_10"], 5 / 6)

    def test_no_relevant_judgments_produces_zero_for_binary_metrics(self) -> None:
        scores = score_order([10, 20], {10: 1, 20: 0})

        self.assertEqual(scores["precision_at_10"], 0.0)
        self.assertEqual(scores["recall_at_10"], 0.0)
        self.assertEqual(scores["f1_at_10"], 0.0)
        self.assertEqual(scores["map_at_10"], 0.0)

    def test_multi_cutoff_exports_preserve_api_captures_and_dataset_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'dataset'
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns('__pycache__', 'tests', 'ranking_at_*'))
            protected = {
                name: (target / name).read_bytes()
                for name in ('golden.jsonl', 'development.jsonl', 'review_notes_filled_v1.3.0.csv',
                             'api_embedding/v1.jsonl', 'api_reranking/v2.jsonl')
            }
            with patch.dict('os.environ', {'LANGCHAIN_TRACING_V2': 'false', 'LANGSMITH_TRACING': 'false'}):
                summary = evaluate(target)
            self.assertEqual(list(summary['cutoffs']), ['5', '10'])
            self.assertEqual(summary['cutoff'], 10)
            for cutoff in (5, 10):
                saved = json.loads((target / f'ranking_at_{cutoff}/summary.json').read_text())
                self.assertEqual(saved, summary['cutoffs'][str(cutoff)])
                for scores in saved['ranking_versions'].values():
                    self.assertIn('top_1_accuracy', scores)
                    self.assertIn(f'top_{cutoff}_accuracy', scores)
                    self.assertIn(f'recall_at_{cutoff}', scores)
            self.assertTrue(all((target / name).read_bytes() == content for name, content in protected.items()))
            self.assertEqual(build_dataset.check(target)['status'], 'passed')

    def test_cutoff_five_uses_only_the_first_five_results(self) -> None:
        scores = score_order(
            [10, 11, 12, 13, 14, 20],
            {10: 3, 20: 2},
            cutoff=5,
        )
        self.assertEqual(scores['precision_at_5'], 0.2)
        self.assertEqual(scores['recall_at_5'], 0.5)
        self.assertEqual(scores['mrr_at_5'], 1.0)


if __name__ == "__main__":
    unittest.main()
