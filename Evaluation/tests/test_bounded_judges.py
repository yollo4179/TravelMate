"""Transport and failure regressions only; no model or network is invoked."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from argparse import Namespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.io import canonical_digest, digest, read_json, write_json
from common.execution.control import ExecutionBlocked, ExecutionSettings, MockExecutionStrategy, Operation, RunControl, RunMode
from common.execution.judge_transport import bounded_completion, completion_document, judge_client, usage_totals
from common.paths import DEFAULT_DATASET
from tracks.search.judge_candidates import AssessmentSettings, assess_case, run as run_candidate_judge
from tracks.search.holdout import read_cases, write_review_csv
from tracks.search.compare_holdout import compare_observations


class BoundedJudgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.case = read_cases(DEFAULT_DATASET.parent / "search-holdout-v1.0.1")[0]
        place = read_json(DEFAULT_DATASET / "generated/corpus.json")[0]
        self.candidate = {"case_id": self.case["case_id"], "candidate_key": "MOCK-" + self.case["case_id"], "query": self.case["input"]["query"], "conditions": json.dumps(self.case["input"]["conditions"], ensure_ascii=False), "place_name": place["name"], "place_region": place["region"], "place_city": place["city"], "description": place["description"], "relevance": "", "rationale": "", "evidence": "", "review_status": "pending", "reviewer": ""}
        self.http = patch("httpx.AsyncClient.send", side_effect=AssertionError("Offline regression attempted HTTP I/O"))
        self.http.start()
        self.addCleanup(self.http.stop)

    def control(self, cap: int, *, mode: RunMode = RunMode.MOCK, parameters: dict | None = None) -> RunControl:
        settings = ExecutionSettings(mode=mode, case_ids=(self.case["case_id"],), max_calls={Operation.JUDGE: cap}, timeout_seconds=1, model="explicit-mock-model", max_output_tokens=700, parameters=parameters or {"judgment_passes": ["first", "independent"], "adjudicate_disagreements": False, "judge_base_url": "https://evaluation.invalid/v1"}, configuration_sha256="synthetic-configuration")
        return RunControl(settings, self.directory / "attempts.jsonl")

    def completion(self, *, valid: bool = True) -> dict:
        quote = self.candidate["description"][:12] if valid else "THIS QUOTE NEVER APPEARED IN THE PROVIDED ORIGINAL"
        judgment = {"candidate_key": self.candidate["candidate_key"], "relevance": "3", "evidence_quotes": [{"field": "description", "quote": quote}], "rationale": "synthetic transport fixture only", "uncertainty_reason": None, "confidence": "high"}
        return {"id": "synthetic-completion", "model": "explicit-mock-model", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"judgments": [judgment]}), "refusal": None}}], "usage": None}

    def responses_for_actual_requests(self, control: RunControl, response: dict):
        async def respond(actual_control: RunControl, case_id: str, request: dict, *, client: object) -> dict:
            self.assertIs(actual_control, control)
            self.assertIsInstance(control.strategy, MockExecutionStrategy)
            control.strategy.responses[canonical_digest(request)] = {"response": copy.deepcopy(response)}
            return await bounded_completion(control, case_id, request, client=client)
        return respond

    def test_mock_judge_does_not_construct_a_paid_client(self) -> None:
        control = self.control(1)
        async def inspect() -> None:
            async with judge_client(control) as client:
                self.assertIsNone(client)
        with patch("openai.AsyncOpenAI", side_effect=AssertionError("No SDK client in MOCK")):
            asyncio.run(inspect())

    def test_live_client_disables_sdk_retry_and_redirects(self) -> None:
        control = self.control(1, mode=RunMode.LIVE)
        context = AsyncMock()
        async def inspect() -> None:
            with patch("openai.AsyncOpenAI", return_value=context) as factory:
                async with judge_client(control, api_key="synthetic-key"):
                    pass
                arguments = factory.call_args.kwargs
                self.assertEqual(arguments["max_retries"], 0)
                self.assertEqual(arguments["timeout"], 1)
                await arguments["http_client"].aclose()
        asyncio.run(inspect())

    def test_invalid_quote_stops_after_one_pass_without_paid_repair(self) -> None:
        control = self.control(3)
        settings = AssessmentSettings(model=control.settings.model, output=self.directory, control=control)
        with patch("tracks.search.judge_candidates.bounded_completion", new=self.responses_for_actual_requests(control, self.completion(valid=False))):
            with self.assertRaises(ValueError):
                asyncio.run(assess_case(None, settings, [self.candidate]))
        self.assertEqual(control.counts[Operation.JUDGE], 1)
        self.assertTrue(control.stopped)
        self.assertEqual(control.last_attempt["response"], self.completion(valid=False))
        self.assertEqual(control.last_attempt["status"], "failed")

    def test_explicit_independent_passes_consume_two_attempts_and_do_not_hide_missing_usage(self) -> None:
        control = self.control(2)
        settings = AssessmentSettings(model=control.settings.model, output=self.directory, control=control)
        with patch("tracks.search.judge_candidates.bounded_completion", new=self.responses_for_actual_requests(control, self.completion())):
            result = asyncio.run(assess_case(None, settings, [self.candidate]))
        self.assertEqual(control.counts[Operation.JUDGE], 2)
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual(control.summary()["real_dispatch_count"], 0)
        self.assertIsNone(usage_totals(result["runs"], RunMode.MOCK)["total_tokens"]["known_sum"])

    def test_failure_or_missing_fixture_stops_following_attempts(self) -> None:
        control = self.control(3)
        client = AsyncMock()
        request = {"model": control.settings.model, "max_completion_tokens": 700}
        with self.assertRaises(ExecutionBlocked):
            asyncio.run(bounded_completion(control, self.case["case_id"], request, client=client))
        with self.assertRaises(ExecutionBlocked):
            asyncio.run(bounded_completion(control, self.case["case_id"], request, client=client))
        self.assertEqual(control.counts[Operation.JUDGE], 1)
        client.chat.completions.create.assert_not_awaited()

    def test_wrong_model_or_output_reservation_is_blocked_before_dispatch(self) -> None:
        control = self.control(1)
        for request in ({"model": "app-model", "max_completion_tokens": 700}, {"model": control.settings.model, "max_completion_tokens": 701}):
            with self.assertRaises(ExecutionBlocked):
                asyncio.run(bounded_completion(control, self.case["case_id"], request, client=None))
        self.assertEqual(control.counts[Operation.JUDGE], 0)

    def test_truncated_response_stops_without_repair_call(self) -> None:
        control = self.control(1)
        completion = self.completion()
        completion["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(ValueError):
            completion_document(control, completion)
        self.assertTrue(control.stopped)

    def test_unobserved_or_mock_labels_do_not_produce_comparison_scores(self) -> None:
        labels = [{**self.candidate, "relevance": "3", "label_source": "mock_judgment"}]
        mapping = [{"case_id": self.case["case_id"], "candidate_key": self.candidate["candidate_key"], "place_id": 378}]
        records = {mode: [{"case_id": self.case["case_id"], "record_source": "spring_search_api", "execution_mode": "MOCK", "ranking_mode": mode, "input_sha256": self.case["input_sha256"]}] for mode in ("SEMANTIC_ONLY", "RERANKED")}
        report = compare_observations([self.case], labels, mapping, records)
        self.assertEqual(report["status"], "not_evaluated")
        self.assertEqual(report["provisional_primary_comparison"]["case_count"], 0)
        self.assertFalse(report["protocol_primary_result_available"])

    def test_candidate_cli_flow_preserves_review_and_labels_mock_outputs_honestly(self) -> None:
        review = self.directory / "review"
        review.mkdir()
        write_review_csv(review / "candidates.csv", [self.candidate], list(self.candidate))
        questions = [{"case_id": self.case["case_id"], "query": self.case["input"]["query"], "conditions": self.candidate["conditions"], "answerability": "", "review_status": "pending", "reviewer": ""}]
        write_review_csv(review / "questions.csv", questions, list(questions[0]))
        dataset = DEFAULT_DATASET.parent / "search-holdout-v1.0.1"
        write_json(review / "review_manifest.json", {"synthetic_fixture": True, "dataset_manifest_sha256": digest(dataset / "manifest.json")})
        original_hashes = {path.name: digest(path) for path in review.iterdir()}
        configuration = self.directory / "execution.json"
        fixtures = self.directory / "mock.json"
        write_json(fixtures, {})
        write_json(configuration, {"mode": "MOCK", "case_ids": [self.case["case_id"]], "max_calls": {"judge": 2}, "timeout_seconds": 1, "model": "explicit-mock-model", "max_output_tokens": 700, "parameters": {"judgment_passes": ["first", "independent"], "adjudicate_disagreements": False, "candidate_file_sha256": digest(review / "candidates.csv")}})
        async def respond(control: RunControl, case_id: str, request: dict, *, client: object) -> dict:
            control.strategy.responses[canonical_digest(request)] = {"response": self.completion()}
            return await bounded_completion(control, case_id, request, client=client)
        arguments = Namespace(dataset=dataset, review_dir=review, config=configuration, mock_responses=fixtures, output_dir=self.directory / "output")
        with patch("tracks.search.judge_candidates.bounded_completion", new=respond), patch("openai.AsyncOpenAI", side_effect=AssertionError("No paid SDK client")):
            asyncio.run(run_candidate_judge(arguments))
        self.assertEqual(original_hashes, {path.name: digest(path) for path in review.iterdir()})
        report = read_json(arguments.output_dir / "summary.json")
        self.assertEqual(report["status"], "mock_regression_only")
        self.assertEqual(report["completed_api_requests"], 0)
        self.assertEqual(report["execution"]["real_dispatch_count"], 0)
        self.assertFalse(report["human_review_complete"])


if __name__ == "__main__":
    unittest.main()
