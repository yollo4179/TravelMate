"""Offline identity and proposed-contract regressions; no inference or search calls."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jsonschema import Draft202012Validator
from common.dataset.io import export_inputs, read_json, read_jsonl
from common.paths import DEFAULT_DATASET, EVALUATION_ROOT
from proposals.place_search_mapping import proposed_search_request, search_case_mapping
from tracks.tool_call.qwen_tokenization import GgufType, read_gguf_metadata
from tracks.tool_call.verify_qwen_tokens import _match_wire, compact, verified_inputs, verify


class ExactQwenAndSearchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prior = EVALUATION_ROOT / "runs/contextual/model-evaluation-preparation-v1/20261101-01"
        cls.saved = EVALUATION_ROOT / "runs/contextual/token-budget-observation-v1/20261101-01/events.jsonl"
        cls.report = EVALUATION_ROOT / "runs/contextual/exact-qwen-and-search-contract-v1/20261102-01"
        cls.cases = read_jsonl(DEFAULT_DATASET / "generated/golden.jsonl")
        cls.search_cases = [case for case in cls.cases if case["expected_response_type"] == "PLACES"]
        cls.schema = read_json(EVALUATION_ROOT / "proposals/plan-independent-place-search.request.schema.json")
        corpus = {place["id"]: place for place in read_json(DEFAULT_DATASET / "generated/corpus.json")}
        cls.hashes = {row["case_id"]: row["input_sha256"] for row in export_inputs(cls.cases, corpus)}

    def test_saved_initial_and_followup_bytes_are_identical_before_counting(self) -> None:
        requests = verified_inputs(self.prior, self.saved)
        self.assertEqual(len(requests), len(self.cases) + 1)
        for row in requests:
            with self.subTest(key=row["key"]):
                self.assertEqual(hashlib.sha256(compact(row["wire"]).encode()).hexdigest(),
                                 row["prior_budget"]["wire_sha256"])
                self.assertEqual(row["input_sha256"], self.hashes[row["prior_budget"]["case_id"]])

    def test_changed_original_or_condition_cannot_borrow_a_previous_wire_hash(self) -> None:
        request = verified_inputs(self.prior, self.saved)[-1]
        modified = copy.deepcopy(request["wire"])
        modified["messages"][-1]["content"] += "\ncondition removed"
        with self.assertRaises(ValueError):
            _match_wire(modified, request["prior_budget"])

    def test_counter_refuses_to_overwrite_existing_evidence_before_loading_native_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("tracks.tool_call.verify_qwen_tokens.NativeQwenVocabulary") as native:
            with self.assertRaises(FileExistsError):
                verify(prior=self.prior, saved_tool_events=self.saved, model=Path("unused"), expected_model_sha256="unused",
                       libraries=Path("unused"), expected_library_sha256="unused", renderer=Path("unused"),
                       expected_renderer_sha256="unused", output=Path(directory))
            native.assert_not_called()

    def test_gguf_reader_stops_before_any_tensor_table_or_weights(self) -> None:
        def encoded_string(value: str) -> bytes:
            encoded = value.encode()
            return struct.pack("<Q", len(encoded)) + encoded

        payload = (b"GGUF" + struct.pack("<IQQ", 3, 399, 2)
                   + encoded_string("general.architecture") + struct.pack("<I", GgufType.STRING) + encoded_string("qwen3")
                   + encoded_string("tokenizer.ggml.tokens") + struct.pack("<IIQ", GgufType.ARRAY, GgufType.STRING, 2)
                   + encoded_string("원문") + encoded_string("조건"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata-only.gguf"
            path.write_bytes(payload + b"TENSOR_BYTES_MUST_NOT_BE_READ")
            metadata = read_gguf_metadata(path)
        self.assertEqual(metadata["tokenizer.ggml.tokens"], ["원문", "조건"])
        self.assertEqual(metadata["inspection.bytes_read_before_tensor_table"], len(payload))
        self.assertEqual(metadata["inspection.tensor_count_not_loaded"], 399)

    def test_invalid_gguf_cannot_be_reported_as_zero_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.gguf"
            for content in (b"", b"GGUF" + struct.pack("<I", 2), b"not-a-model"):
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    read_gguf_metadata(path)

    def test_every_existing_search_case_fits_the_proposed_schema_without_a_plan(self) -> None:
        validator = Draft202012Validator(self.schema)
        for case in self.search_cases:
            with self.subTest(case_id=case["case_id"]):
                projection = search_case_mapping(case, self.hashes[case["case_id"]])
                request = projection["proposed_search_request"]
                validator.validate(request)
                self.assertEqual(request["query"], case["input"]["query"])
                self.assertEqual(request["excludePlaceIds"], case["input"]["conditions"]["exclude_place_ids"])
                self.assertNotIn("planningRequest", request)
                self.assertFalse(projection["application_adapter_implemented"])
                self.assertFalse(projection["search_executed"])

    def test_existing_get_transport_subset_is_not_labelled_search_quality_success(self) -> None:
        mapped = [search_case_mapping(case, self.hashes[case["case_id"]]) for case in self.search_cases]
        self.assertTrue(any(row["current_get_filter_transport_supported"] for row in mapped))
        self.assertTrue(any(not row["current_get_filter_transport_supported"] for row in mapped))
        self.assertTrue(all(not row["runtime_corpus_verified"] for row in mapped))
        self.assertTrue(all(not row["current_llm_tool_works_without_plan"] for row in mapped))

    def test_radius_units_anchor_and_history_are_preserved_once(self) -> None:
        for case in self.search_cases:
            mapped = search_case_mapping(case, self.hashes[case["case_id"]])
            area = case["input"]["conditions"].get("area")
            if area:
                self.assertEqual(mapped["proposed_search_request"]["area"]["radiusMeters"], area["radius_meters"])
                self.assertEqual(mapped["area_provenance"]["center_place_id"], area["center_place_id"])
            self.assertEqual(mapped["conversation_history_once"], case["input"].get("messages") or [])

    def test_unknown_filter_or_distance_cannot_be_silently_dropped(self) -> None:
        case = copy.deepcopy(self.search_cases[0])
        case["input"]["conditions"]["unimplemented_filter"] = True
        with self.assertRaises(ValueError):
            proposed_search_request(case)
        area_case = copy.deepcopy(next(case for case in self.search_cases if case["input"]["conditions"].get("area")))
        area_case["input"]["conditions"]["area"]["distance_method"] = "walking_time"
        with self.assertRaises(ValueError):
            proposed_search_request(area_case)

    def test_proposed_contract_rejects_plan_fields_and_conflicting_histories(self) -> None:
        request = proposed_search_request(self.search_cases[0])
        request["planningRequest"] = {}
        self.assertTrue(list(Draft202012Validator(self.schema).iter_errors(request)))
        case = copy.deepcopy(self.search_cases[0])
        case["input"]["messages"] = [{"role": "user", "content": "original history"}]
        case["input"]["conditions"]["conversation"] = [{"role": "user", "content": "different history"}]
        with self.assertRaises(ValueError):
            search_case_mapping(case, self.hashes[case["case_id"]])


if __name__ == "__main__":
    unittest.main()
