"""LangSmith integration wiring tests without sending external requests."""
from __future__ import annotations

import sys
import unittest
from contextlib import contextmanager
from os import environ
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ragas_support.backend import RagasBackend
from ragas_support.langsmith_observability import evaluation_span
from ragas_support.settings import EvaluatorSettings


class ObservabilityTests(unittest.TestCase):
    def test_openai_async_client_is_wrapped_for_langsmith_tracing(self) -> None:
        settings = EvaluatorSettings("gpt-4.1-mini", "text-embedding-3-small", "test-key")
        wrapped_client = object()

        with (
            patch("openai.AsyncOpenAI") as openai_client,
            patch("langsmith.wrappers.wrap_openai", return_value=wrapped_client) as wrap_openai,
        ):
            client = RagasBackend().create_client(settings)

        self.assertIs(client, wrapped_client)
        openai_client.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
        )
        wrap_openai.assert_called_once_with(openai_client.return_value)

    def test_metric_span_records_case_inputs_and_score_outputs(self) -> None:
        class FakeRun:
            instances: list["FakeRun"] = []

            def __init__(self, **kwargs: object) -> None:
                self.inputs = kwargs["inputs"]
                self.outputs: dict[str, object] | None = None
                self.instances.append(self)

            def post(self) -> None:
                return None

            def end(self, *, outputs: dict[str, object], end_time: object) -> None:
                self.outputs = outputs

            def patch(self) -> None:
                return None

        @contextmanager
        def fake_tracing_context(**_: object):
            yield

        with (
            patch.dict(environ, {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "test-key",
                "LANGCHAIN_PROJECT": "test-project",
            }),
            patch("langsmith.run_trees.RunTree", FakeRun),
            patch("langsmith.run_helpers.tracing_context", fake_tracing_context),
        ):
            with evaluation_span(
                operation="travelmate.ranking_metrics",
                case_id="case-1",
                strategy_version="v1_semantic_only",
                metric_name="ranking_metrics_at_10",
                inputs={"query": "test query", "cutoff": 10},
            ) as trace:
                self.assertIsNotNone(trace)
                trace.set_attribute("evaluation.ndcg_at_10", 1.0)
                trace.set_attribute("evaluation.map_at_10", 0.5)

        self.assertEqual(FakeRun.instances[0].inputs, {
            "case_id": "case-1",
            "strategy_version": "v1_semantic_only",
            "metric_name": "ranking_metrics_at_10",
            "query": "test query",
            "cutoff": 10,
        })
        self.assertEqual(FakeRun.instances[0].outputs, {
            "evaluation.ndcg_at_10": 1.0,
            "evaluation.map_at_10": 0.5,
        })


if __name__ == "__main__":
    unittest.main()
