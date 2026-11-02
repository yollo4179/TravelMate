"""Preparation checks only; no inference, application HTTP, or search requests."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.io import export_inputs, read_json, read_jsonl
from common.paths import DEFAULT_DATASET
from tracks.tool_call.preparation import (
    BudgetStatus, ConnectionStatus, budget_summary, case_connections, collect_qwen_metadata, propose_pilot,
)


class ModelPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = read_jsonl(DEFAULT_DATASET / "generated/golden.jsonl")
        cls.connections = case_connections(DEFAULT_DATASET)

    def test_every_existing_case_is_inventoried_with_the_original_export_hash(self) -> None:
        corpus = {place["id"]: place for place in read_json(DEFAULT_DATASET / "generated/corpus.json")}
        expected = {row["case_id"]: row["input_sha256"] for row in export_inputs(self.cases, corpus)}
        actual = {row["case_id"]: row["input_sha256"] for row in self.connections}
        self.assertEqual(expected, actual)
        self.assertTrue(all(not row["full_frozen_case_compatible"] for row in self.connections))

    def test_api_projection_preserves_question_and_history_without_inventing_trip_conditions(self) -> None:
        indexed = {case["case_id"]: case for case in self.cases}
        for row in self.connections:
            with self.subTest(case_id=row["case_id"]):
                source = indexed[row["case_id"]]["input"]
                request = row["minimal_api_request"]
                self.assertEqual(request["message"], source["query"])
                self.assertIsNone(request["planningRequest"])
                self.assertEqual([message["content"] for message in request["history"]],
                                 [message["content"] for message in source.get("messages") or []])
                self.assertTrue(all(message["role"] in {"USER", "ASSISTANT"} for message in request["history"]))

    def test_plan_and_modification_cases_cannot_become_legacy_plan_success(self) -> None:
        for row in self.connections:
            if row["expected_response_type"] not in {"PLAN", "PLAN_DIFF"}:
                continue
            with self.subTest(case_id=row["case_id"]):
                self.assertEqual(row["connection"], ConnectionStatus.CONTRACT_BLOCKED)
                self.assertFalse(row["pilot_candidate"])

    def test_no_inference_or_remote_endpoint_is_available_to_metadata_collection(self) -> None:
        with patch("tracks.tool_call.preparation.urlopen") as network:
            for origin in ("https://api.openai.com", "http://remote.example", "http://localhost:11434/api/chat",
                           "http://secret@localhost:11434", "http://localhost:11434?path=/api/generate"):
                with self.subTest(origin=origin), self.assertRaises(ValueError):
                    collect_qwen_metadata(origin, "qwen3:8b")
            network.assert_not_called()

    def test_metadata_only_uses_explicit_read_only_methods_and_excludes_local_blob_path(self) -> None:
        requests = []

        class MetadataResponse:
            def __enter__(self) -> MetadataResponse:
                return self

            def __exit__(self, *exception: object) -> None:
                return None

            def read(self, maximum_bytes: int) -> bytes:
                return json.dumps({"model_info": {}, "modelfile": "private blob path"}).encode()

        def capture(request: object, **options: object) -> MetadataResponse:
            requests.append(request)
            return MetadataResponse()

        with patch("tracks.tool_call.preparation.urlopen", side_effect=capture):
            captured = collect_qwen_metadata("http://localhost:11434", "qwen3:8b")
        self.assertEqual([request.full_url for request in requests], [
            "http://localhost:11434/api/version", "http://localhost:11434/api/tags",
            "http://localhost:11434/api/ps", "http://localhost:11434/api/show",
        ])
        self.assertEqual([request.get_method() for request in requests], ["GET", "GET", "GET", "POST"])
        self.assertNotIn("private blob path", json.dumps(captured))
        self.assertEqual(captured["inference_calls"], 0)

    def test_unavailable_metadata_is_not_reported_as_budget_pass(self) -> None:
        with patch("tracks.tool_call.preparation.urlopen", side_effect=OSError("offline")):
            captured = collect_qwen_metadata("http://localhost:11434", "qwen3:8b")
        self.assertTrue(all(row["status"] == "UNVERIFIED" for row in captured["responses"].values()))
        self.assertEqual(budget_summary([{"status": BudgetStatus.UNVERIFIED}]), {
            "PASS": 0, "EXCEEDED": 0, "UNVERIFIED": 1,
        })

    def test_proposal_stays_unapproved_and_does_not_borrow_the_judge_as_an_app_model(self) -> None:
        budgets = [{"case_id": row["case_id"], "scope": "INITIAL_API_REQUEST", "status": BudgetStatus.EXCEEDED}
                   for row in self.connections]
        proposal = propose_pilot(self.connections, budgets)
        self.assertFalse(proposal["approved"])
        self.assertFalse(proposal["executed"])
        self.assertFalse(proposal["current_budget_ready"])
        self.assertIsNone(proposal["app_gpt_model"])
        self.assertEqual(proposal["judge_calls_proposed"], 0)
        self.assertEqual(proposal["inference_calls_authorized_now"], 0)
        self.assertTrue(set(proposal["case_ids"]) <= {row["case_id"] for row in self.connections if row["pilot_candidate"]})
        proposed_count = len(proposal["case_ids"]) * proposal["repetitions_proposed"]
        self.assertEqual(proposal["conditional_pilot_inference_cap"], proposed_count)


if __name__ == "__main__":
    unittest.main()
