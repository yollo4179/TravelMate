"""Exercise the production SQL builder with a mocked database only."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import time
from typing import Any
import unittest
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from app.contextual.observation_search import ObservationFilter
from app.contextual.retrieval import resolve_retrieval_strategy
from test_contextual_subject_filter import mock_database


class IndependentSearchFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_region_city_exclusions_and_meter_radius_reach_where_before_top_k(self) -> None:
        module = ast.parse((ROOT / "app/kafka_runtime.py").read_text(encoding="utf-8"))
        runtime = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "KafkaRuntime")
        method = next(node for node in runtime.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_retrieve_candidates")
        namespace = {"Any": Any, "ObservationFilter": ObservationFilter, "resolve_retrieval_strategy": resolve_retrieval_strategy,
                     "time": time, "tracer": lambda: MagicMock(), "RETRIEVE_TOP_K": 30}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<production-retrieval>", "exec"), namespace)
        for use_relations in (False, True):
            pool, connection = mock_database({})
            connection.fetch.return_value = []
            target = MagicMock(database_pool=pool, use_relation_vectors=use_relations)
            filters = {"region": "서울", "city": "종로", "category": "공원", "exclude_place_ids": [378, 379],
                       "area": {"type": "CIRCLE", "center": {"lat": 37.57, "lon": 126.98}, "radius_meters": 500}}
            await namespace["_retrieve_candidates"](target, {"filters": filters}, "[0]")
            query, *parameters = connection.fetch.await_args.args
            self.assertIn("region = $2", query)
            self.assertIn("city = $3", query)
            self.assertIn("category = $4", query)
            self.assertIn("NOT (place_id = ANY($5::bigint[]))", query)
            self.assertIn("6371000 * 2 * asin", query)
            self.assertLess(query.index("NOT (place_id"), query.rindex("LIMIT"))
            self.assertEqual(parameters, ["[0]", "서울", "종로", "공원", [378, 379], 37.57, 37.57, 126.98, 500, "[0]", 30])


if __name__ == "__main__":
    unittest.main()
