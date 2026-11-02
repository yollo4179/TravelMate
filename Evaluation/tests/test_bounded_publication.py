"""Offline transport, source binding and incomplete-observation regressions."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.io import canonical_digest, digest, read_json, write_json, write_jsonl
from common.execution.control import ExecutionBlocked, ExecutionSettings, Operation, RunControl, RunMode
from common.observability.langsmith_transport import LangSmithTransport, langsmith_transport, publish_artifact
from common.paths import DEFAULT_DATASET
from tracks.search.publish_metrics import build_artifact
from tracks.search.publish_batch_experiment import build_legacy_artifact
from tracks.search.summarize_langsmith import query_runs, summarize_records


class BoundedPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.case_id = "PLR-TM-palaces-01"
        self.run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "offline-run-fixture"))
        self.project_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "offline-project-fixture"))
        self.parameters = {"langsmith_api_url": "https://evaluation.invalid", "project_name": "offline-fixture", "project_id": self.project_id, "run_id": self.run_id, "publication_purpose": "verified_search_quality", "feedback_metrics": ["reranking.ndcg_at_10"], "publication_timestamp": "2026-11-02T00:00:00+00:00"}
        self.artifact = {"case_ids": [self.case_id], "quality_status": "verified_search_observations", "metrics": {"reranking.ndcg_at_10": 0.5}, "source_sha256": {"synthetic-input": "fixture-hash"}}
        self.http = patch("httpx.AsyncClient.send", side_effect=AssertionError("Offline regression attempted HTTP I/O"))
        self.http.start()
        self.addCleanup(self.http.stop)

    def control(self, *, publish: int = 2, reads: int = 2, mode: RunMode = RunMode.MOCK, parameters: dict | None = None) -> RunControl:
        settings = ExecutionSettings(mode=mode, case_ids=(self.case_id,), max_calls={Operation.PUBLISH: publish, Operation.OBSERVATION_READ: reads}, timeout_seconds=1, model=None, max_output_tokens=None, parameters=parameters or self.parameters, configuration_sha256="synthetic-configuration")
        return RunControl(settings, self.directory / "attempts.jsonl")

    def transport(self, control: RunControl, *, fail_write: bool = False, mismatch: bool = False) -> LangSmithTransport:
        transport = LangSmithTransport(control)
        original = transport.request
        stored_feedback: dict[str, dict] = {}
        async def mocked(operation: Operation, case_id: str, method: str, route: str, payload: dict | None = None) -> dict:
            if method == "POST" and route == "/feedback":
                stored_feedback[payload["id"]] = payload
            response = {}
            if method == "GET" and route.startswith("/feedback/"):
                response = stored_feedback[route.rsplit("/", 1)[-1]]
            if method == "GET" and route.startswith("/runs/"):
                response = {"id": self.run_id, "session_id": self.project_id, "outputs": {} if mismatch else self.artifact}
            request = {"method": method, "url": "https://evaluation.invalid" + route, "body": payload}
            control.strategy.responses[canonical_digest(request)] = {"response": {"status_code": 400 if fail_write else 200, "raw_body": "original failure" if fail_write else json.dumps(response)}}
            return await original(operation, case_id, method, route, payload)
        transport.request = mocked
        return transport

    def test_mock_publication_counts_every_http_request_and_never_claims_live_verification(self) -> None:
        control = self.control()
        result = asyncio.run(publish_artifact(control, self.transport(control), name="synthetic-regression", artifact=self.artifact))
        self.assertEqual(control.counts[Operation.PUBLISH], 2)
        self.assertEqual(control.counts[Operation.OBSERVATION_READ], 2)
        self.assertEqual(result["status"], "mock_regression_only")
        self.assertFalse(result["feedback_readback_verified"])
        self.assertEqual(result["real_dispatch_count"], 0)
        requests = [event["request"] for event in control.events if event["status"] == "started"]
        self.assertFalse(any(request["method"] == "PATCH" for request in requests))

    def test_insufficient_call_budget_blocks_before_any_write(self) -> None:
        control = self.control(publish=1, mode=RunMode.LIVE)
        transport = AsyncMock()
        with self.assertRaises(ExecutionBlocked):
            asyncio.run(publish_artifact(control, transport, name="synthetic-regression", artifact=self.artifact))
        transport.request.assert_not_awaited()
        self.assertEqual(sum(control.counts.values()), 0)

    def test_unobserved_quality_cannot_be_published_live(self) -> None:
        control = self.control(mode=RunMode.LIVE)
        artifact = {**self.artifact, "quality_status": "not_evaluated", "metrics": {}}
        with self.assertRaises(ExecutionBlocked):
            asyncio.run(publish_artifact(control, AsyncMock(), name="synthetic-regression", artifact=artifact))
        self.assertEqual(sum(control.counts.values()), 0)

    def test_http_failure_is_preserved_without_retry_or_readback(self) -> None:
        control = self.control()
        with self.assertRaises(ValueError):
            asyncio.run(publish_artifact(control, self.transport(control, fail_write=True), name="synthetic-regression", artifact=self.artifact))
        self.assertEqual(control.counts[Operation.PUBLISH], 1)
        self.assertEqual(control.counts[Operation.OBSERVATION_READ], 0)
        self.assertEqual(control.last_attempt["response"]["raw_body"], "original failure")
        self.assertTrue(control.stopped)

    def test_mismatched_readback_is_not_success_and_is_not_polled(self) -> None:
        control = self.control()
        with self.assertRaises(ValueError):
            asyncio.run(publish_artifact(control, self.transport(control, mismatch=True), name="synthetic-regression", artifact=self.artifact))
        self.assertEqual(control.counts[Operation.OBSERVATION_READ], 1)
        self.assertTrue(control.stopped)

    def test_mock_transport_does_not_read_credentials_or_open_http_client(self) -> None:
        control = self.control()
        async def inspect() -> None:
            async with langsmith_transport(control, "ABSENT_EVAL_KEY") as transport:
                self.assertIsNone(transport.client)
        with patch("httpx.AsyncClient", side_effect=AssertionError("No HTTP client in MOCK")):
            asyncio.run(inspect())

    def test_historical_report_cannot_become_verified_numeric_feedback(self) -> None:
        control = self.control(parameters={**self.parameters, "publication_purpose": "archive_legacy_report"})
        artifact = {**self.artifact, "quality_status": "legacy_report_only"}
        with self.assertRaises(ExecutionBlocked):
            asyncio.run(publish_artifact(control, AsyncMock(), name="synthetic-regression", artifact=artifact))
        self.assertEqual(sum(control.counts.values()), 0)

    def test_building_a_summary_does_not_promote_mock_search_into_measured_quality(self) -> None:
        collection = self.directory / "collection"
        write_json(collection / "collection_summary.json", {"execution_mode": "MOCK", "status": "completed", "dataset_manifest_sha256": "synthetic-manifest"})
        runs = []
        for label, filename, mode in (("embedding", "embedding_records.jsonl", "SEMANTIC_ONLY"), ("reranking", "reranked_records.jsonl", "RERANKED")):
            record = {"case_id": self.case_id, "execution_mode": "MOCK", "ranking_mode": mode}
            write_jsonl(collection / filename, [record])
            output = self.directory / label
            write_jsonl(output / "outputs/records.jsonl", [record])
            write_jsonl(output / "scores/results.jsonl", [{"case_id": self.case_id}])
            write_json(output / "summary.json", {"status": "partial", "responses_sha256": digest(collection / filename), "dataset_manifest_sha256": "synthetic-manifest", "code_metrics_and_gpt_scores": {}})
            runs.append(output)
        artifact = build_artifact(collection, *runs)
        self.assertEqual(artifact["quality_status"], "not_evaluated")
        self.assertEqual(artifact["metrics"], {})
        write_jsonl(collection / "embedding_records.jsonl", [{"case_id": "tampered"}])
        with self.assertRaises(ValueError):
            build_artifact(collection, *runs)

    def test_span_queries_stop_at_explicit_page_limit(self) -> None:
        parameters = {**self.parameters, "max_pages": 1, "page_size": 10, "query_filter": "explicit-fixture-filter"}
        control = self.control(reads=1, parameters=parameters)
        transport = LangSmithTransport(control)
        payload = {"session": [self.project_id], "filter": "explicit-fixture-filter", "limit": 10}
        request = {"method": "POST", "url": "https://evaluation.invalid/runs/query", "body": payload}
        control.strategy.responses[canonical_digest(request)] = {"response": {"status_code": 200, "raw_body": json.dumps({"runs": [], "cursors": {"next": "next-unfetched-page"}})}}
        records = [{"case_id": self.case_id, "trace_id": "1" * 32}]
        capture = asyncio.run(query_runs(control, transport, records))
        self.assertTrue(capture["truncated"])
        self.assertEqual(control.counts[Operation.OBSERVATION_READ], 1)

    def test_missing_trace_stage_and_timestamps_are_not_filled(self) -> None:
        trace = "1" * 32
        records = [{"case_id": self.case_id, "trace_id": trace, "execution_mode": "LIVE", "execution_status": "completed", "ranking_mode": "RERANKED"}]
        capture = {"execution_mode": "LIVE", "runs": [{"id": "synthetic-span", "name": "travelmate.search", "start_time": "2026-11-02T00:00:00+00:00", "end_time": "2026-11-02T00:00:01+00:00", "extra": {"metadata": {"OTEL_TRACE_ID": trace}}}]}
        report = summarize_records(records, capture)
        self.assertEqual(report["status"], "partial")
        self.assertIn("reranking.model_inference", report["missing_stages_by_trace"][trace])
        self.assertEqual(report["live_stage_latency"][0]["device"], "not_observed")
        capture["runs"][0].pop("end_time")
        report = summarize_records(records, capture)
        self.assertEqual(report["live_stage_latency"], [])
        self.assertEqual(report["missing_duration_by_stage"]["travelmate.search"], 1)

    def test_mock_span_durations_never_enter_live_latency_means(self) -> None:
        report = summarize_records([{"case_id": self.case_id, "execution_mode": "MOCK"}], {"execution_mode": "MOCK", "runs": []})
        self.assertEqual(report["live_stage_latency"], [])
        self.assertEqual(report["cases_without_trace_binding"], [self.case_id])
        self.assertEqual(report["status"], "partial")


if __name__ == "__main__":
    unittest.main()
