"""Resident resource/invalidity/protocol checks with mocked vocabulary and no network."""
from __future__ import annotations

from contextlib import ExitStack
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "Evaluation")]
from Server.token_budget import resident_qwen as resident
from Server.token_budget.exact_qwen_counter import MODEL_DIGEST, TEMPLATE_SHA256, digest


class ResidentQwenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        show = json.loads((ROOT / "Evaluation/runs/contextual/model-evaluation-preparation-v1/20261101-01/qwen-show.json").read_text(encoding="utf-8"))
        first = json.loads((ROOT / "Evaluation/runs/contextual/runtime-qwen-independent-search-v1/20261102-01/current-native-wires.jsonl").read_text(encoding="utf-8").split("\n")[0])
        self.envelope = {"wire": json.dumps(first["wire"], ensure_ascii=False, separators=(",", ":")), "show": show,
                         "version": {"version": "0.40.13"}, "tags": {"models": [{"name": "qwen3:8b", "digest": MODEL_DIGEST}]}}
        self.stack.enter_context(patch.object(resident.importlib.metadata, "version", return_value="0.22.2"))
        self.original_fingerprints = resident.asset_fingerprints
        self.fingerprints = self.stack.enter_context(patch.object(resident, "asset_fingerprints", return_value={"mock": (1, 2, 3)}))
        self.loader = self.stack.enter_context(patch.object(resident, "load_verified_assets", return_value=SimpleNamespace(
            model=Path("mock-model"), libraries=Path("mock-lib"), renderer=Path("mock-renderer"), metadata={})))
        self.native = MagicMock()
        self.native.special_policy.return_value = {"add_bos": False, "add_eos": False, "vocabulary_size": 151936}
        self.native.encode.side_effect = lambda prompt: list(prompt.encode("utf-8"))
        self.native.decode.side_effect = lambda identifiers, size: bytes(identifiers)
        self.native_factory = self.stack.enter_context(patch.object(resident, "NativeQwenVocabulary", return_value=self.native))
        self.independent = MagicMock()
        self.independent.encode.side_effect = lambda prompt, **options: SimpleNamespace(ids=list(prompt.encode("utf-8")))
        self.independent_factory = self.stack.enter_context(patch.object(resident, "independent_byte_bpe", return_value=self.independent))
        self.renderer = MagicMock()
        self.renderer.render.side_effect = lambda envelope, request_id: {"prompt": envelope["wire"]}
        self.renderer_factory = self.stack.enter_context(patch.object(resident, "PersistentRenderer", return_value=self.renderer))

    def test_one_initialization_reuses_both_tokenizers_but_recounts_each_full_input(self) -> None:
        session = resident.QwenTokenizerSession({}, self.envelope)
        self.addCleanup(session.close)
        first = session.count(self.envelope, "first")
        changed = copy.deepcopy(self.envelope)
        wire = json.loads(changed["wire"])
        wire["messages"].append({"role": "tool", "content": "과거 공사로 통행할 수 없었다. 조건 보존."})
        changed["wire"] = json.dumps(wire, ensure_ascii=False, separators=(",", ":"))
        second = session.count(changed, "second")
        repeat = session.count(self.envelope, "repeat")
        self.assertEqual(first["tokenIdsSha256"], repeat["tokenIdsSha256"])
        self.assertNotEqual(first["tokenIdsSha256"], second["tokenIdsSha256"])
        self.assertEqual([first["sequence"], second["sequence"], repeat["sequence"]], [1, 2, 3])
        self.assertEqual(first["workerSessionId"], second["workerSessionId"])
        self.native_factory.assert_called_once()
        self.independent_factory.assert_called_once()
        self.loader.assert_called_once()
        self.renderer_factory.assert_called_once()
        self.assertEqual(self.native.encode.call_count, 3)
        self.assertEqual(self.independent.encode.call_count, 3)
        session.close()
        session.close()
        self.native.close.assert_called_once()

    def test_asset_or_metadata_change_invalidates_before_reusing_old_tokenizer(self) -> None:
        session = resident.QwenTokenizerSession({}, self.envelope)
        self.fingerprints.return_value = {"mock": (1, 2, 4)}
        with self.assertRaises(resident.IdentityChangedError):
            session.count(self.envelope, "changed-file")
        self.assertTrue(session.closed)
        self.native.encode.assert_not_called()
        self.native.close.assert_called_once()
        self.fingerprints.return_value = {"mock": (1, 2, 3)}
        next_session = resident.QwenTokenizerSession({}, self.envelope)
        altered = copy.deepcopy(self.envelope)
        altered["show"]["template"] = "changed template"
        with self.assertRaises(resident.MetadataIdentityError):
            next_session.count(altered, "changed-template")
        self.assertTrue(next_session.closed)

    def test_token_disagreement_closes_session_and_cannot_return_a_count(self) -> None:
        session = resident.QwenTokenizerSession({}, self.envelope)
        self.independent.encode.side_effect = lambda *arguments, **options: SimpleNamespace(ids=[999])
        with self.assertRaises(ValueError):
            session.count(self.envelope, "mismatch")
        self.assertTrue(session.closed)
        self.assertEqual(session.sequence, 0)
        self.native.close.assert_called_once()
        with self.assertRaises(resident.IdentityChangedError):
            session.count(self.envelope, "cannot-reuse")

    def test_protocol_init_then_two_counts_uses_one_session_and_closes_on_eof(self) -> None:
        frames = [{"requestId": identifier, "operation": operation, "payload": self.envelope}
                  for identifier, operation in (("init", "INIT"), ("one", "COUNT"), ("two", "COUNT"))]
        source = io.BytesIO("".join(json.dumps(frame) + "\n" for frame in frames).encode())
        output = io.BytesIO()
        resident.serve({}, source, output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row["requestId"] for row in responses], ["init", "one", "two"])
        self.assertEqual([row["status"] for row in responses], ["READY", "COUNTED", "COUNTED"])
        self.assertEqual(len({row["sessionId"] for row in responses}), 1)
        self.assertEqual(responses[2]["payload"]["sequence"], 2)
        self.native_factory.assert_called_once()
        self.native.close.assert_called_once()

    def test_protocol_cannot_count_before_init_or_continue_after_error(self) -> None:
        frames = [{"requestId": "bad", "operation": "COUNT", "payload": self.envelope},
                  {"requestId": "later", "operation": "INIT", "payload": self.envelope}]
        output = io.BytesIO()
        resident.serve({}, io.BytesIO("".join(json.dumps(frame) + "\n" for frame in frames).encode()), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["status"], "ERROR")
        self.native_factory.assert_not_called()

    def test_real_file_fingerprints_detect_updates_without_reading_weights(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for filename in ("model", "renderer", "manifest", "libllama.dll", "profile"):
                (base / filename).write_bytes(b"mock")
            profile = {"model_path": str(base / "model"), "renderer_path": str(base / "renderer"),
                       "manifest_path": str(base / "manifest"), "library_directory": str(base), "profile_path": str(base / "profile")}
            before = self.original_fingerprints(profile)
            (base / "model").write_bytes(b"modified mock model")
            self.assertNotEqual(before, self.original_fingerprints(profile))


if __name__ == "__main__":
    unittest.main()
