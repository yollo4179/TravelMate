"""Ranking metrics use the same graded human judgments for both strategies."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluate_ranking import score_order


class RankingMetricTests(unittest.TestCase):
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

    def test_cutoff_five_uses_only_the_first_five_results(self) -> None:
        scores = score_order(
            [10, 11, 12, 13, 14, 20],
            {10: 3, 20: 2},
            cutoff=5,
        )

        self.assertEqual(scores["precision_at_5"], 0.2)
        self.assertEqual(scores["recall_at_5"], 0.5)
        self.assertEqual(scores["mrr_at_5"], 1.0)


if __name__ == "__main__":
    unittest.main()
