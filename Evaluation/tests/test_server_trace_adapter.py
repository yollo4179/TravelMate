"""MOCK adapter regression, not a model quality evaluation."""
from __future__ import annotations

import copy
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.io import canonical_digest, export_inputs, read_json, read_jsonl, write_jsonl
from common.runs.runner import evaluate
from common.judge.runner import JudgeSettings, judge_prompt
from common.paths import DEFAULT_DATASET
from tracks.end_to_end.score import provenance_metrics
from tracks.end_to_end.score import evaluate_record
from common.observability.server_trace import message_is_observed
from tracks.state.score import state_metrics
from tracks.tool_call.convert_server_trace import RecordMode, convert_records


class ServerTraceAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = read_jsonl(DEFAULT_DATASET / "generated/golden.jsonl")
        cls.case = next(case for case in cls.cases if case["case_id"] == "PLR-TM-palaces-01")
        corpus = {place["id"]: place for place in read_json(DEFAULT_DATASET / "generated/corpus.json")}
        cls.exported = export_inputs([cls.case], corpus)[0]

    def fixture(self) -> tuple[list[dict], list[dict]]:
        case = self.case
        request = {"message": case["input"]["query"]}
        raw_body = json.dumps(request, ensure_ascii=False)
        artifact = [{"placeId": 378, "name": "창경궁"}]
        tool_result = {
            "callId": "call-1", "name": "search_places",
            "arguments": json.dumps({"query": case["input"]["query"], "limit": 1}),
            "status": "SUCCEEDED", "type": "PLACES", "publicData": artifact, "resultId": "result-1",
        }
        response = {
            "type": "PLACES", "message": "모의 설명", "data": artifact,
            "requestId": "request-1", "turnId": "turn-1", "conversationId": case["input"]["conversationId"],
            "primaryResultId": "result-1", "termination": "COMPLETED", "toolResults": [tool_result],
        }
        specifications = [
            ("MODEL_TURN", {"toolCalls": [{"id": "call-1", "name": "search_places", "arguments": tool_result["arguments"]}]}),
            ("TOOL_RESULT", {"result": tool_result}),
            ("TURN_RESULT", response),
            ("API_REQUEST", {"rawBody": raw_body, "bodySha256": hashlib.sha256(raw_body.encode()).hexdigest()}),
            ("API_RESPONSE", {"httpStatus": 200, "response": response}),
        ]
        events = [{
            "eventId": f"event-{index}", "event": kind, "payload": copy.deepcopy(payload),
            "requestId": "request-1", "turnId": "turn-1", "mode": "MOCK", "jobId": None,
            "caseId": case["case_id"], "inputSha256": self.exported["input_sha256"],
        } for index, (kind, payload) in enumerate(specifications)]
        bindings = [{
            "case_id": case["case_id"], "input_sha256": self.exported["input_sha256"],
            "request_id": "request-1", "api_request": request,
        }]
        return events, bindings

    def convert(self, events: list[dict], bindings: list[dict]) -> dict:
        return convert_records(events, bindings, [self.exported], mode=RecordMode.MOCK)[0]

    def test_reuses_existing_input_hash_and_preserves_actual_calls_data_and_explanation(self) -> None:
        events, bindings = self.fixture()
        record = self.convert(events, bindings)
        self.assertEqual(record["input_sha256"], self.exported["input_sha256"])
        self.assertNotEqual(record["api_input_sha256"], record["input_sha256"])
        self.assertEqual(record["tool_calls"][0]["function"]["arguments"], events[1]["payload"]["result"]["arguments"])
        self.assertEqual(provenance_metrics(record, record["response"]), {
            "server_data_unchanged": 1.0, "server_type_matches_primary_result": 1.0,
        })
        self.assertEqual(record["quality_status"], "mock_regression_only")
        self.assertEqual(record["model"], "not_observed")
        self.assertIn("provider_call_observations_incomplete", record["compatibility_gaps"])
        self.assertNotIn("observations", record)

    def test_absent_state_snapshots_remain_unobserved_in_the_existing_scorer(self) -> None:
        events, bindings = self.fixture()
        record = self.convert(events, bindings)
        case = next(case for case in self.cases if case["expectations"]["state"] is not None)
        scores = state_metrics(case, record, record["response"])
        self.assertIsNone(scores["observed_plan_state_preserved"])
        self.assertIsNone(scores["observed_commit_version_matches"])

    def test_strict_provider_arguments_and_server_projection_are_preserved_separately(self) -> None:
        events, bindings = self.fixture()
        provider_arguments = json.dumps({"query": self.case["input"]["query"], "limit": None,
            "region": None, "city": None, "category": None, "exclude_place_ids": None, "area": None})
        server_arguments = json.dumps({**json.loads(provider_arguments), "limit": 10})
        for event in events:
            payload = event["payload"]
            if event["event"] == "MODEL_TURN":
                payload["toolCalls"][0]["arguments"] = server_arguments
            if event["event"] == "TOOL_RESULT":
                payload["result"]["arguments"] = server_arguments
            if event["event"] == "TURN_RESULT":
                payload["toolResults"][0]["arguments"] = server_arguments
            if event["event"] == "API_RESPONSE":
                payload["response"]["toolResults"][0]["arguments"] = server_arguments
        native_call = {"type": "function_call", "call_id": "call-1", "name": "search_places", "arguments": provider_arguments}
        provider_event = {**copy.deepcopy(events[0]), "eventId": "mock-provider", "event": "MODEL_CALL",
            "payload": {"stage": "FINISHED", "provider": "OPENAI", "model": "MOCK", "status": "SUCCEEDED",
                "dispatched": True, "receipt": {"nativeToolCalls": [native_call], "usage": {}}}}
        adaptation = {**copy.deepcopy(events[0]), "eventId": "mock-adaptation", "event": "TOOL_ARGUMENT_ADAPTATION",
            "payload": {"callId": "call-1", "originalArguments": provider_arguments,
                "serverArguments": server_arguments, "status": "ADAPTED"}}
        record = self.convert([*events, provider_event, adaptation], bindings)
        self.assertEqual(provider_arguments, record["provider_tool_calls"][0]["arguments"])
        self.assertEqual(server_arguments, record["tool_calls"][0]["function"]["arguments"])
        self.assertEqual("server_contract", record["tool_calls_representation"])
        self.assertEqual([adaptation], record["argument_adaptations"])
        self.assertEqual("mock_regression_only", record["quality_status"])
        self.assertFalse(record["observation_coverage"]["tool_call"])

    def test_mock_or_budget_blocked_calls_cannot_become_successful_quality_metrics(self) -> None:
        events, bindings = self.fixture()
        record = self.convert(events, bindings)
        scores = evaluate_record(self.case, record)["metrics"]
        self.assertIsNone(scores["tool_precision"])
        self.assertIsNone(scores["tool_argument_schema_valid"])
        self.assertIsNone(scores["ndcg_at_5"])
        self.assertEqual(scores["server_data_unchanged"], 1.0)
        self.assertFalse(message_is_observed(record))
        self.assertIsNone(record["usage_summary"]["inputTokens"]["known_sum"])

    def test_unobserved_native_quality_fields_fail_closed_even_in_live_mode(self) -> None:
        events, bindings = self.fixture()
        record = self.convert(events, bindings)
        record["record_source"] = "spring_execution_live"
        record["execution_mode"] = "LIVE"
        record.pop("observation_coverage")
        scores = evaluate_record(self.case, record)["metrics"]
        self.assertIsNone(scores["tool_recall"])
        self.assertIsNone(scores["response_type_accuracy"])
        self.assertFalse(message_is_observed(record))

    def test_mock_records_cannot_be_relabelled_live(self) -> None:
        events, bindings = self.fixture()
        with self.assertRaises(ValueError):
            convert_records(events, bindings, [self.exported], mode=RecordMode.LIVE)
        events[0]["mode"] = "LIVE"
        with self.assertRaises(ValueError):
            self.convert(events, bindings)

    def test_rejects_missing_input_trace_hash_changes_and_rebound_api_payloads(self) -> None:
        for mutation in ("missing-request", "wrong-hash", "wrong-api-request", "wrong-wire-hash", "wrong-conversation"):
            with self.subTest(mutation=mutation):
                events, bindings = self.fixture()
                if mutation == "missing-request":
                    events = [event for event in events if event["event"] != "API_REQUEST"]
                if mutation == "wrong-hash":
                    bindings[0]["input_sha256"] = "0" * 64
                if mutation == "wrong-api-request":
                    bindings[0]["api_request"]["message"] = "다른 요청"
                if mutation == "wrong-wire-hash":
                    next(event for event in events if event["event"] == "API_REQUEST")["payload"]["bodySha256"] = "0" * 64
                if mutation == "wrong-conversation":
                    for event in events:
                        if event["event"] == "TURN_RESULT":
                            event["payload"]["conversationId"] = "fabricated"
                        if event["event"] == "API_RESPONSE":
                            event["payload"]["response"]["conversationId"] = "fabricated"
                with self.assertRaises(ValueError):
                    self.convert(events, bindings)

    def test_rejects_replaced_primary_artifacts(self) -> None:
        events, bindings = self.fixture()
        for event in events:
            if event["event"] == "TURN_RESULT":
                event["payload"]["data"] = [{"placeId": 999}]
            if event["event"] == "API_RESPONSE":
                event["payload"]["response"]["data"] = [{"placeId": 999}]
        with self.assertRaises(ValueError):
            self.convert(events, bindings)

    def test_keeps_pending_job_and_draft_as_native_types_without_faking_preview(self) -> None:
        for response_type in ("PLANNING_JOB", "DRAFT"):
            with self.subTest(response_type=response_type):
                events, bindings = self.fixture()
                artifact = ({"jobId": "job-mock", "status": "QUEUED"} if response_type == "PLANNING_JOB"
                            else {"planId": 77, "pins": [{"placeId": 378, "sequence": 1}]})
                for event in events:
                    if event["event"] == "MODEL_TURN":
                        event["payload"]["toolCalls"][0]["name"] = "generate_plan"
                        event["payload"]["toolCalls"][0]["arguments"] = "{}"
                    if event["event"] == "TOOL_RESULT":
                        event["payload"]["result"].update(type=response_type, name="generate_plan", arguments="{}", publicData=artifact)
                    if event["event"] in {"TURN_RESULT", "API_RESPONSE"}:
                        response = event["payload"] if event["event"] == "TURN_RESULT" else event["payload"]["response"]
                        response["type"] = response_type
                        response["data"] = artifact
                        response["toolResults"][0].update(type=response_type, name="generate_plan", arguments="{}", publicData=artifact)
                record = self.convert(events, bindings)
                self.assertEqual(record["response"]["type"], response_type)
                self.assertIn("native_response_type_has_no_legacy_envelope_equivalent", record["compatibility_gaps"])
                self.assertEqual(record["tool_calls"][0]["function"]["name"], "generate_plan")
                self.assertNotIn("applied", record["response"]["data"])

    def test_existing_java_case_binding_matches_the_frozen_export(self) -> None:
        fixture_path = Path(__file__).resolve().parents[2] / "Server/TravelMate/src/test/resources/token-budget/existing-case-binding.json"
        fixture = read_json(fixture_path)
        self.assertEqual(fixture["case_id"], self.case["case_id"])
        self.assertEqual(fixture["input_sha256"], self.exported["input_sha256"])
        self.assertEqual(fixture["query"], self.exported["model_input"]["query"])

    def test_mock_records_never_construct_a_paid_judge_client(self) -> None:
        events, bindings = self.fixture()
        record = self.convert(events, bindings)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            responses = output / "mock-records.jsonl"
            write_jsonl(responses, [record])
            with patch("common.runs.runner.score_message", new=AsyncMock()) as judge:
                result = asyncio.run(evaluate(
                    root=DEFAULT_DATASET, group=None, cases=[self.case], responses_path=responses,
                    output=output / "reports", use_judge=True, settings=JudgeSettings("unused-mock", ""),
                ))
            judge.assert_not_awaited()
            self.assertEqual(result, 1)
            scored = read_jsonl(output / "reports/scores/results.jsonl")[0]
            self.assertEqual(scored["judge_status"], "not_evaluated")
            self.assertIsNone(scored["code"]["metrics"]["tool_precision"])

    def test_jsonl_preserves_unicode_line_separators_inside_original_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.jsonl"
            originals = [{"originalText": "부정\u0085조건\u2028과거\u2029기록"}]
            write_jsonl(path, originals)
            self.assertEqual(read_jsonl(path), originals)

    def test_native_judge_receives_actual_tool_evidence_and_api_input(self) -> None:
        events, bindings = self.fixture()
        evidence = {"originalText": "과거에 연결됐지만 현재 통행 여부는 알 수 없다.", "sourceId": "source-mock"}
        for event in events:
            if event["event"] == "TOOL_RESULT":
                event["payload"]["modelData"] = evidence
        record = self.convert(events, bindings)
        _, _, supplied = judge_prompt(self.case, record, {"query": "NEVER_DELIVERED"}, "mock rubric")
        self.assertIn(evidence["originalText"], supplied)
        self.assertNotIn("NEVER_DELIVERED", supplied)


if __name__ == "__main__":
    unittest.main()
