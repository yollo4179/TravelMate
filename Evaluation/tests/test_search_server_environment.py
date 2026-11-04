from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.experiments.search_server import search_environment

EXAMPLE = Path(__file__).resolve().parents[1] / "experiments/server-environment.example.json"
SEARCH_DATABASE = "postgresql://evaluator:unused@127.0.0.1:55433/travelmate_search_evaluation"


def environment(**overrides: str) -> dict[str, str]:
    values = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    values.update(
        EVAL_DB_USERNAME="evaluator",
        EVAL_DB_PASSWORD="unused",
        EVAL_JWT_SECRET="x" * 48,
        # The OpenAI budget-policy checks are covered elsewhere; this test isolates the search database rule.
        EVAL_LLM_PROVIDER="QWEN",
        EVAL_EMBEDDING_DATABASE_URL=SEARCH_DATABASE,
    )
    values.update(overrides)
    return values


class SearchEnvironmentTests(unittest.TestCase):
    def test_search_may_use_its_own_evaluation_database_like_operation(self) -> None:
        isolated, port = search_environment(environment())
        self.assertEqual(isolated["DATABASE_URL"], SEARCH_DATABASE)
        self.assertEqual(port, 18000)
        self.assertEqual(isolated["KAFKA_RECOMMENDATION_REQUESTS_TOPIC"], "travelmate.evaluation.recommendation-requests.v1")

    def test_search_database_must_be_a_dedicated_evaluation_database(self) -> None:
        for url in ("postgresql://evaluator:unused@127.0.0.1:5432/travel_search_db",
                    "mysql://evaluator:unused@127.0.0.1:3306/travelmate_search_evaluation"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                search_environment(environment(EVAL_EMBEDDING_DATABASE_URL=url))


if __name__ == "__main__":
    unittest.main()
