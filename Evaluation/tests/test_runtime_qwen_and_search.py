"""Runtime worker and observation projection regressions, with no network or inference."""
from __future__ import annotations

import copy
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "Evaluation")]
from Server.token_budget import exact_qwen_counter as worker
from common.dataset.io import read_json, read_jsonl
from tracks.tool_call.place_search_projection import conditions_covered, project_search_call, history_covered


class RuntimeQwenAndSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        prior = ROOT / "Evaluation/runs/contextual/exact-qwen-and-search-contract-v1/20261102-01"
        show = read_json(ROOT / "Evaluation/runs/contextual/model-evaluation-preparation-v1/20261101-01/qwen-show.json")
        self.wire = read_json(prior / "token-counts/first-wire.json")
        self.envelope = {"wire": json.dumps(self.wire, ensure_ascii=False, separators=(",", ":")), "show": show,
                         "version": {"version": "0.40.13"},
                         "tags": {"models": [{"name": "qwen3:8b", "digest": worker.MODEL_DIGEST}]}}

    def test_exact_profile_identity_accepts_saved_native_request_but_rejects_changes(self) -> None:
        self.assertEqual(worker.validate_identity(self.envelope), self.wire)
        for section, field, value in (("version", "version", "new-version"), ("show", "template", "changed"),
                                      ("show", "template_source", "jinja"), ("show", "system", "different system")):
            changed = copy.deepcopy(self.envelope)
            changed[section][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                worker.validate_identity(changed)
        changed = copy.deepcopy(self.envelope)
        changed["tags"]["models"][0]["digest"] = "different-model"
        with self.assertRaises(ValueError):
            worker.validate_identity(changed)

    def test_unsupported_payloads_block_before_local_model_access(self) -> None:
        for mutation in ({"think": True}, {"images": ["base64"]}, {"raw": True}, {"format": {"type": "object"}}):
            envelope = copy.deepcopy(self.envelope)
            wire = {**self.wire, **mutation}
            envelope["wire"] = json.dumps(wire)
            with self.subTest(mutation=mutation), patch.object(worker, "file_sha256") as hash_file:
                with self.assertRaises(ValueError):
                    worker.count(envelope, {})
                hash_file.assert_not_called()

    def test_tokenizer_version_and_local_identity_failure_do_not_render_or_infer(self) -> None:
        with patch.object(importlib.metadata, "version", return_value="unverified"), patch.object(worker.subprocess, "run") as render:
            with self.assertRaises(ValueError):
                worker.count(self.envelope, {})
            render.assert_not_called()
        profile = {"model_path": "model", "renderer_path": "renderer", "library_directory": "lib", "manifest_path": "manifest"}
        with patch.object(importlib.metadata, "version", return_value="0.22.2"), patch.object(worker, "file_sha256", return_value="mismatch"), patch.object(worker.subprocess, "run") as render:
            with self.assertRaises(ValueError):
                worker.count(self.envelope, profile)
            render.assert_not_called()

    def test_projection_is_separate_from_native_call_and_cannot_grant_a_score(self) -> None:
        call = {"id": "s1", "type": "function", "function": {"name": "search_places", "arguments":
                '{"query":"궁궐","region":null,"city":null,"category":null,"exclude_place_ids":[],"area":null,"limit":10}'}}
        original = copy.deepcopy(call)
        effective = {"query": "궁궐", "region": "서울", "city": None, "category": None, "excludePlaceIds": [378],
                     "area": None, "limit": 10, "rankingMode": "RERANKED"}
        projected = project_search_call(call, {"searchContractVersion": "place-search-v2", "searchCriteria": effective,
                                              "filterProvenance": {"region": "SEARCH_CONTEXT"}})
        self.assertEqual(call, original)
        self.assertEqual(json.loads(projected["projected_tool_call"]["function"]["arguments"])["region"], "서울")
        self.assertEqual(projected["native_arguments"]["region"], None)
        self.assertEqual(projected["status"], "PROJECTED_NOT_SCORED")
        self.assertFalse(projected["legacy_exact_args_automatically_accepted"])
        self.assertTrue(conditions_covered({"region": "서울", "exclude_place_ids": [378]}, effective))
        self.assertFalse(conditions_covered({"region": "서울", "exclude_place_ids": [379]}, effective))
        conversation = [{"role": "user", "content": "exclude the previous place"}]
        self.assertTrue(history_covered({"messages": conversation}, {"history": [{"role": "USER", "content": conversation[0]["content"]}]}))
        self.assertFalse(history_covered({"conditions": {"conversation": conversation}}, {"history": []}))

    def test_token_id_disagreement_and_lost_original_bytes_fail_closed(self) -> None:
        rendered = {"wire_sha256": worker.digest(self.envelope["wire"]), "template_sha256": worker.TEMPLATE_SHA256,
                    "prompt": "full original", "prompt_sha256": worker.digest("full original")}
        metadata = {"general.architecture": "qwen3", "tokenizer.ggml.model": "gpt2", "tokenizer.ggml.pre": "qwen2",
                    "qwen3.context_length": 40960}
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"layers": [{"digest": "sha256:" + worker.MODEL_SHA256}]}), encoding="utf-8")
            profile = {"manifest_path": str(manifest), "model_path": "model", "library_directory": "lib", "renderer_path": "renderer"}
            for same_ids, same_bytes in ((False, True), (True, False), (True, True)):
                native = MagicMock()
                native.special_policy.return_value = {"add_bos": False, "add_eos": False, "vocabulary_size": 151936}
                native.encode.return_value = [1, 2]
                native.decode.return_value = b"full original" if same_bytes else b"truncated"
                independent = MagicMock()
                independent.encode.return_value.ids = [1, 2] if same_ids else [1, 3]
                with patch.object(importlib.metadata, "version", return_value="0.22.2"), \
                     patch.object(worker, "file_sha256", side_effect=[worker.MODEL_DIGEST, worker.MODEL_SHA256, worker.RENDERER_SHA256]), \
                     patch.object(worker, "read_gguf_metadata", return_value=metadata), \
                     patch.object(worker.subprocess, "run", return_value=MagicMock(stdout=json.dumps(rendered).encode())), \
                     patch.object(worker, "NativeQwenVocabulary") as vocabulary, \
                     patch.object(worker, "independent_byte_bpe", return_value=independent):
                    vocabulary.return_value.__enter__.return_value = native
                    if same_ids and same_bytes:
                        self.assertEqual(worker.count(self.envelope, profile)["inputTokens"], 2)
                    else:
                        with self.assertRaises(ValueError):
                            worker.count(self.envelope, profile)

    def test_all_existing_search_filters_and_history_have_a_lossless_api_projection(self) -> None:
        mappings = read_jsonl(ROOT / "Evaluation/runs/contextual/exact-qwen-and-search-contract-v1/20261102-01/search-case-mapping.jsonl")
        self.assertEqual(len(mappings), 85)
        for row in mappings:
            with self.subTest(case_id=row["case_id"]):
                self.assertTrue(conditions_covered(row["original_conditions"], row["proposed_search_request"]))
        radius = next(row for row in mappings if row["proposed_search_request"]["area"] is not None)
        changed = copy.deepcopy(radius["proposed_search_request"])
        changed["area"]["radiusMeters"] += 1
        self.assertFalse(conditions_covered(radius["original_conditions"], changed))


if __name__ == "__main__":
    unittest.main()
