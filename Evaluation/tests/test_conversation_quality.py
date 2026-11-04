"""Synthetic regression cases verify the evaluator, never the quality of a live LLM."""
from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.io import canonical_digest, read_json, read_jsonl, write_json
from common.execution.control import ExecutionBlocked, ExecutionSettings
from common.paths import EVALUATION_ROOT
from tracks.conversation.cases import DEFAULT_SUITE, load_cases
from tracks.conversation.review import export_review, summarize
from tracks.conversation.run import collect, prepared_cases, validate_contract
from tracks.conversation.score import score_case


EXAMPLES = EVALUATION_ROOT / "experiments/conversation-smoke"


class ConversationQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name)
        cls.bindings = read_json(EXAMPLES / "offline-bindings.json")
        cls.settings = ExecutionSettings.load(EXAMPLES / "offline.json")
        cls.cases = {case["case_id"]: case for case in load_cases(DEFAULT_SUITE, cls.settings.case_ids, cls.bindings)}
        with patch("httpx.AsyncClient", side_effect=AssertionError("MOCK constructed a network client")):
            cls.summary = asyncio.run(collect(cls.arguments(cls.directory / "run")))
        cls.records = {record["case_id"]: record for record in read_jsonl(cls.directory / "run/records.jsonl")}
        cls.events = read_jsonl(cls.directory / "run/events.jsonl")
        cls.contract = read_json(cls.directory / "run/server-contract.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @staticmethod
    def arguments(output: Path) -> argparse.Namespace:
        return argparse.Namespace(suite=DEFAULT_SUITE, config=EXAMPLES / "offline.json", bindings=EXAMPLES / "offline-bindings.json",
                                  mock_responses=EXAMPLES / "offline-fixtures.json", output_dir=output, events=None, execute_live=False)

    def mutable(self, case_id: str = "PLR-TM-palaces-03") -> tuple[dict, list[dict]]:
        record = copy.deepcopy(self.records[case_id])
        events = copy.deepcopy([event for event in self.events if event["caseId"] == case_id])
        return record, events

    def synchronize_native(self, record: dict, events: list[dict]) -> None:
        for event in events:
            if event["event"] == "TURN_RESULT":
                event["payload"] = copy.deepcopy(record["native_response"])
            if event["event"] == "API_RESPONSE":
                event["payload"]["response"] = copy.deepcopy(record["native_response"])
            if event["event"] == "MODEL_TURN" and not event["payload"]["toolCalls"]:
                answer = json.loads(event["payload"]["content"])
                answer["message"] = record["native_response"]["message"]
                answer["citations"] = record["native_response"]["citations"]
                event["payload"]["content"] = json.dumps(answer, ensure_ascii=False)

    def score(self, record: dict, events: list[dict]) -> dict:
        return score_case(self.cases[record["case_id"]], record, events, self.contract)

    def test_nine_offline_cases_complete_without_becoming_model_quality_successes(self) -> None:
        self.assertEqual(self.summary["automated_pass_count"], 9)
        self.assertEqual(self.summary["quality_pass_count"], 0)
        self.assertFalse(self.summary["all_quality_passed"])
        self.assertEqual(self.summary["execution"]["attempt_counts"], {"runtime_read": 2, "conversation": 9})
        self.assertEqual(self.summary["execution"]["real_dispatch_count"], 0)

    def test_existing_questions_and_hashes_are_preserved_and_gold_never_reaches_model(self) -> None:
        hashes = {"PLR-TM-palaces-01": "13f07e1370f08c3962a159bbf18ff3ef60b7a5b2d03f1d550a34c96f70f9598b",
                  "PLR-TM-palaces-03": "42a6a1b0fb5c40e8be6c37f1cf5e685c982b4d927151646eb6b2467478d8246d"}
        for identifier, value in hashes.items():
            self.assertEqual(self.cases[identifier]["input_sha256"], value)
        for record in self.records.values():
            request = json.loads(record["http_request"]["raw_body"])
            self.assertEqual(set(request), {"message", "planningRequest", "history", "searchContext"})
            self.assertNotIn("expected", request)
            self.assertNotIn("message_example", request)

    def test_prepared_query_and_explicit_metadata_cannot_silently_change(self) -> None:
        for key, value in (("region", "부산"), ("query", "질문과 다른 검색어"), ("excludePlaceIds", [999])):
            record, events = self.mutable()
            preparation = next(event for event in events if event["event"] == "EVIDENCE_PREPARATION")
            preparation["payload"]["modelData"]["searchCriteria"][key] = value
            self.assertEqual(self.score(record, events)["automated_status"], "failed")

    def test_server_pre_retrieval_is_not_a_model_selected_tool(self) -> None:
        record, events = self.mutable()
        score = self.score(record, events)
        self.assertTrue(score["checks"]["pre_retrieval_observed"])
        self.assertEqual(score["model_tool_calls"], [])
        self.assertTrue(score["checks"]["model_tool_selection"])

    def test_no_events_leaves_decisions_citations_and_quality_unassessed(self) -> None:
        record, _ = self.mutable()
        score = self.score(record, [])
        self.assertEqual(score["automated_status"], "not_assessed")
        self.assertIsNone(score["checks"]["model_tool_selection"])
        self.assertIsNone(score["checks"]["citation_original_membership"])
        self.assertFalse(score["quality_observed"])

    def test_wrong_request_case_hash_or_turn_cannot_bind_an_observation(self) -> None:
        for mutation in ("caseId", "inputSha256"):
            record, events = self.mutable()
            events[0][mutation] = "wrong"
            self.assertFalse(self.score(record, events)["checks"]["trace_binding"])
        record, events = self.mutable()
        record["native_response"]["turnId"] = "stale-turn"
        self.synchronize_native(record, events)
        self.assertFalse(self.score(record, events)["checks"]["trace_binding"])

    def test_citation_from_another_place_or_source_fails(self) -> None:
        for field, value in (("placeId", 208), ("sourceId", "wrong-source"), ("quote", "원문에 없는 인용")):
            record, events = self.mutable()
            record["native_response"]["citations"][0][field] = value
            self.synchronize_native(record, events)
            self.assertFalse(self.score(record, events)["checks"]["citation_original_membership"])

    def test_generated_context_does_not_count_as_original_quote(self) -> None:
        record, events = self.mutable()
        for event in events:
            if event["event"] == "EVIDENCE_PREPARATION":
                event["payload"]["modelData"]["candidates"][0]["selectedEvidence"][0]["generatedSupplement"] = {"context_text": "생성된 표현"}
        record["native_response"]["citations"][0]["quote"] = "생성된 표현"
        self.synchronize_native(record, events)
        self.assertFalse(self.score(record, events)["checks"]["citation_original_membership"])

    def test_unsupported_tool_and_wrong_job_argument_fail(self) -> None:
        record, events = self.mutable("CONV-JOB-owned")
        for event in events:
            if event["event"] == "MODEL_TURN":
                event["payload"]["toolCalls"][0]["arguments"] = '{"job_id":"00000000-0000-4000-8000-000000000099"}'
        self.assertFalse(self.score(record, events)["checks"]["tool_arguments"])
        record, events = self.mutable()
        for event in events:
            if event["event"] == "MODEL_TURN":
                event["payload"]["toolCalls"] = [{"id": "bad", "name": "reserve_ticket", "arguments": "{}"}]
        self.assertFalse(self.score(record, events)["checks"]["model_tool_selection"])

    def test_schema_invalid_final_text_is_a_failure(self) -> None:
        record, events = self.mutable()
        for event in events:
            if event["event"] == "MODEL_TURN":
                event["payload"]["content"] = "```json\n{}\n```"
        self.assertFalse(self.score(record, events)["checks"]["answer_json_schema"])

    def test_http200_fallback_cannot_pass(self) -> None:
        record, events = self.mutable()
        record["native_response"].update(termination="COUNT_UNAVAILABLE", messageSource="SERVER_FALLBACK")
        self.synchronize_native(record, events)
        score = self.score(record, events)
        self.assertEqual(score["automated_status"], "failed")
        self.assertFalse(score["checks"]["completed"])

    def test_literal_quote_match_does_not_prove_recommendation_reason(self) -> None:
        record, events = self.mutable()
        record["native_response"]["message"] = "창경궁에는 지금도 왕실 가족이 살고 있으니 방문하면 만날 수 있어요."
        self.synchronize_native(record, events)
        score = self.score(record, events)
        self.assertEqual(score["automated_status"], "passed")
        self.assertEqual(score["semantic_status"], "not_reviewed")
        self.assertEqual(summarize([score], expected_count=1)["quality_pass_count"], 0)

    def test_semantic_review_is_bound_and_cannot_turn_mock_into_live_success(self) -> None:
        record, events = self.mutable()
        score = self.score(record, events)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.csv"
            export_review(path, [score])
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                row.update(verdict="PASS", reviewer="offline-test-reviewer", rationale="synthetic review exercise")
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            summary = summarize([score], expected_count=1, review_path=path)
            self.assertFalse(summary["all_quality_passed"])
            self.assertEqual(summary["quality_pass_count"], 0)
            rows[0]["record_sha256"] = "different-run"
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            with self.assertRaises(ValueError):
                summarize([score], expected_count=1, review_path=path)

    def test_cleared_backups_are_not_runtime_dependencies(self) -> None:
        for case in self.cases.values():
            self.assertNotIn(".local-backups", json.dumps(case, ensure_ascii=False))
        self.assertNotIn(".local-backups", json.dumps(self.contract, ensure_ascii=False))

    def test_missing_owned_job_binding_is_not_guessed(self) -> None:
        with self.assertRaises(ValueError):
            load_cases(DEFAULT_SUITE, ("CONV-JOB-owned",), {})

    def test_actual_tool_cap_one_wrong_actor_or_model_blocks_before_conversation(self) -> None:
        for field, value in (("max_tool_calls", 1), ("model", "unexpected"), ("evaluation_user", {"user_id": "another-user"})):
            contract = copy.deepcopy(self.contract)
            contract[field] = value
            with self.subTest(field=field), self.assertRaises(ExecutionBlocked):
                validate_contract(contract, list(self.cases.values()), self.settings)

    def test_preflight_failure_stops_before_any_model_app_request(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = read_json(EXAMPLES / "offline-fixtures.json")
            fixture["contract"]["max_tool_calls"] = 1
            write_json(root / "fixture.json", fixture)
            arguments = self.arguments(root / "run")
            arguments.mock_responses = root / "fixture.json"
            with patch("httpx.AsyncClient", side_effect=AssertionError("MOCK created HTTP client")):
                summary = asyncio.run(collect(arguments))
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["execution"]["attempt_counts"], {"runtime_read": 1})
            self.assertEqual(len(summary["not_run"]), 9)

    def test_live_template_has_no_plan_creation_and_requires_no_fake_job(self) -> None:
        settings = ExecutionSettings.load(EXAMPLES / "live.template.json")
        arguments = self.arguments(self.directory / "unused")
        arguments.bindings = None
        cases = prepared_cases(arguments, settings)
        self.assertEqual(len(cases), 2)
        self.assertFalse(any(case["creates_plan"] for case in cases))

    def test_wrong_argument_stops_collection_at_that_case(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = read_json(EXAMPLES / "offline-fixtures.json")
            for event in fixture["cases"]["CONV-SEARCH-exclude-first"]["events"]:
                if event["event"] == "MODEL_TURN":
                    args = json.loads(event["payload"]["toolCalls"][0]["arguments"])
                    args["exclude_place_ids"] = []
                    event["payload"]["toolCalls"][0]["arguments"] = json.dumps(args)
            write_json(root / "fixture.json", fixture)
            arguments = self.arguments(root / "run");arguments.mock_responses = root / "fixture.json"
            summary = asyncio.run(collect(arguments))
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["execution"]["attempt_counts"], {"runtime_read": 2, "conversation": 7})
            self.assertEqual(summary["not_run"], ["CONV-JOB-owned", "CONV-PLAN-create"])

    def test_invalid_server_response_is_reported_instead_of_crashing_the_scorer(self) -> None:
        record, events = self.mutable()
        record["native_response"] = ["not an envelope"]
        score = self.score(record, events)
        self.assertEqual(score["automated_status"], "failed")
        self.assertFalse(score["checks"]["response_object"])


if __name__ == "__main__":
    unittest.main()
