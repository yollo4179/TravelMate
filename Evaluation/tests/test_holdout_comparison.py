"""Protect unknown exclusion and family weighting in provisional holdout comparisons."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracks.search.compare_holdout import Eligibility, METRICS, classify, cluster_interval, compare_complete
from tracks.search.holdout import RankingMode


class HoldoutComparisonTests(unittest.TestCase):
    def test_unknown_excludes_even_a_query_with_a_known_positive(self) -> None:
        self.assertEqual(classify(["3", "unknown"]), Eligibility.UNKNOWN)
        self.assertEqual(classify(["0", "unknown"]), Eligibility.UNKNOWN)

    def test_empty_and_no_relevant_pools_are_different(self) -> None:
        self.assertEqual(classify([]), Eligibility.NO_CANDIDATES)
        self.assertEqual(classify(["0", "1"]), Eligibility.COMPLETE_NO_RELEVANT)
        self.assertEqual(classify(["0", "2"]), Eligibility.COMPLETE_POSITIVE)

    def test_paraphrases_do_not_increase_a_familys_weight(self) -> None:
        rows = [
            {"case_id": f"C{index}", "family_id": family,
             RankingMode.SEMANTIC_ONLY: dict.fromkeys(METRICS, 0.0),
             RankingMode.RERANKED: dict.fromkeys(METRICS, improvement)}
            for index, (family, improvement) in enumerate([("A", 1.0), ("A", 1.0), ("B", 0.0)])
        ]
        result = compare_complete(rows)
        self.assertEqual(result["family_count"], 2)
        self.assertEqual(result["metrics"]["ndcg_at_10"]["paired_delta"], 0.5)

    def test_bootstrap_is_deterministic_and_retains_zero(self) -> None:
        interval = cluster_interval([0.0, 0.4], repetitions=1000)
        self.assertEqual(interval, cluster_interval([0.0, 0.4], repetitions=1000))
        self.assertEqual(interval, [0.0, 0.4])
        self.assertIsNone(cluster_interval([]))
