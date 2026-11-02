"""Offline projection regressions for existing frozen search cases, not quality scores."""
from __future__ import annotations

import asyncio
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.io import canonical_digest, digest, read_json, read_jsonl, write_json
from common.execution.control import ExecutionSettings, Operation, RunControl
from common.observability.search_records import search_quality_observed, search_record_error
from common.paths import DEFAULT_DATASET
from tracks.search.api_contract import RankingMode, search_body, unsupported_conditions
from tracks.search.collect_live import collect_cases, selected_v14_inputs


class FrozenSearchProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.search_cases = [
            case
            for case in read_jsonl(DEFAULT_DATASET / "generated/golden.jsonl")
            if "search" in case["evaluation_tracks"]
        ]
        cls.radius_case = next(
            case
            for case in cls.search_cases
            if case["case_id"] == "PLR-TM-family_parks-04"
        )

    def test_actual_radius_case_sends_coordinates_without_inventing_an_id_filter(self) -> None:
        original = copy.deepcopy(self.radius_case)
        for mode in RankingMode:
            with self.subTest(mode=mode):
                body = search_body(self.radius_case, mode, 20)
                self.assertEqual(body["area"], {
                    "type": "CIRCLE",
                    "center": {"lat": 37.5206092598, "lon": 127.1150682209},
                    "radiusMeters": 500,
                })
                self.assertEqual(
                    body["excludePlaceIds"],
                    original["input"]["conditions"].get("exclude_place_ids") or [],
                )
                self.assertNotIn("center_place_id", json.dumps(body))
                self.assertNotIn("centerPlaceId", json.dumps(body))
                self.assertEqual(unsupported_conditions(self.radius_case["input"]["conditions"]), ["conversation"])
        self.assertEqual(self.radius_case, original)
        self.assertEqual(original["input"]["conditions"]["area"]["center_place_id"], 311)

    def test_all_85_existing_search_cases_convert_in_both_modes_without_input_changes(self) -> None:
        self.assertEqual(len(self.search_cases), 85)
        before = canonical_digest(self.search_cases)
        for case in self.search_cases:
            for mode in RankingMode:
                with self.subTest(case_id=case["case_id"], mode=mode):
                    body = search_body(case, mode, 20)
                    self.assertEqual(body["query"], case["input"]["query"])
                    self.assertEqual(body["rankingMode"], mode.value)
                    self.assertEqual(set(body), {
                        "query", "region", "city", "category",
                        "excludePlaceIds", "area", "limit", "rankingMode",
                    })
        self.assertEqual(canonical_digest(self.search_cases), before)

    def test_history_support_is_separate_from_successful_request_conversion(self) -> None:
        coverage = Counter(
            tuple(unsupported_conditions(case["input"]["conditions"]))
            for case in self.search_cases
        )
        self.assertEqual(coverage, {(): 65, ("conversation",): 20})
        for case in self.search_cases:
            if case["input"]["conditions"].get("conversation"):
                with self.subTest(case_id=case["case_id"]):
                    body = search_body(case, RankingMode.RERANKED, 20)
                    self.assertNotIn("conversation", body)
                    self.assertEqual(unsupported_conditions(case["input"]["conditions"]), ["conversation"])

    def test_center_id_never_supplies_missing_coordinates(self) -> None:
        case = copy.deepcopy(self.radius_case)
        del case["input"]["conditions"]["area"]["center"]
        with self.assertRaises(KeyError):
            search_body(case, RankingMode.RERANKED, 20)

    def test_other_unknown_area_fields_still_fail(self) -> None:
        case = copy.deepcopy(self.radius_case)
        case["input"]["conditions"]["area"]["unrecognized_filter"] = 311
        with self.assertRaises(ValueError):
            search_body(case, RankingMode.RERANKED, 20)

    def test_mock_batch_preserves_center_provenance_and_separate_history_block(self) -> None:
        identifiers = [self.search_cases[0]["case_id"], self.radius_case["case_id"]]
        cases = selected_v14_inputs(DEFAULT_DATASET, tuple(identifiers))
        original = copy.deepcopy(cases)
        modes = list(RankingMode)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            configuration = output / "configuration.json"
            write_json(configuration, {
                "mode": "MOCK",
                "case_ids": identifiers,
                "max_calls": {"search": len(cases) * len(modes)},
                "timeout_seconds": 1,
                "model": None,
                "max_output_tokens": None,
                "parameters": {
                    "ranking_modes": [mode.value for mode in modes],
                    "dataset_manifest_sha256": digest(DEFAULT_DATASET / "manifest.json"),
                    "server_url": "http://evaluation.invalid",
                    "response_limit": 20,
                    "require_comparable_runtime": False,
                },
            })
            fixtures: dict[str, Any] = {}
            for case in cases:
                for mode in modes:
                    raw_body = json.dumps(
                        search_body(case, mode, 20),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    request = {
                        "method": "POST",
                        "url": "http://evaluation.invalid/api/places/search",
                        "route": "/api/places/search",
                        "raw_body": raw_body,
                        "body_sha256": hashlib.sha256(raw_body.encode("utf-8")).hexdigest(),
                    }
                    fixtures[canonical_digest(request)] = {
                        "response": {"status_code": 200, "raw_body": "[]"},
                    }
            control = RunControl(
                ExecutionSettings.load(configuration),
                output / "attempts.jsonl",
                mock_responses=fixtures,
            )
            client = AsyncMock()
            with patch("httpx.AsyncClient.send", side_effect=AssertionError("Offline test attempted HTTP I/O")):
                asyncio.run(collect_cases(
                    cases=cases,
                    dataset=DEFAULT_DATASET,
                    output=output,
                    control=control,
                    runtime={"corpus_sha256": digest(DEFAULT_DATASET / "generated/corpus.json")},
                    client=client,
                ))
            client.request.assert_not_awaited()
            summary = read_json(output / "collection_summary.json")
            self.assertEqual(summary["status"], "partial")
            self.assertEqual(summary["recorded_case_modes"], 4)
            self.assertEqual(control.counts[Operation.SEARCH], 2)
            selected = read_jsonl(output / "selected_inputs.jsonl")
            for row, case in zip(selected, original, strict=True):
                self.assertEqual(row["original_input"], case["input"])
                self.assertEqual(row["input_sha256"], case["input_sha256"])
            for filename in ("embedding_records.jsonl", "reranked_records.jsonl"):
                records = read_jsonl(output / filename)
                for case, record in zip(cases, records, strict=True):
                    self.assertIsNone(search_record_error(case, record))
                    self.assertEqual(record["execution_mode"], "MOCK")
                    self.assertFalse(record["dispatched"])
                    self.assertFalse(search_quality_observed(record))
                record = records[1]
                self.assertEqual(records[0]["execution_status"], "completed")
                self.assertEqual(record["execution_status"], "not_run")
                self.assertEqual(record["unsupported_conditions"], ["conversation"])
                self.assertEqual(record["error_type"], "unsupported_original_conditions")
                self.assertIsNone(record["http_response"])
                self.assertIsNone(record["ranked_place_ids"])
                self.assertEqual(record["requested_conditions"]["area"]["center_place_id"], 311)
                self.assertEqual(record["input_sha256"], original[1]["input_sha256"])
                self.assertEqual(
                    record["evaluation_projection"]["server_body"],
                    json.loads(record["http_request"]["raw_body"]),
                )
                self.assertNotIn("center_place_id", record["http_request"]["raw_body"])
        self.assertEqual(cases, original)


if __name__ == "__main__":
    unittest.main()
