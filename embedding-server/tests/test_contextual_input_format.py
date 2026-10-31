"""입력 형식 변경의 원문 보존·비교 격리·기존 기록 호환성을 검증한다."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))
from app.contextual.agent import request_payload
from app.contextual.artifacts import collect_bundle, load_record, revalidate_record
from app.contextual.cli import run
from app.contextual.input_format import InputVersion, explicit_chunks
from app.contextual.input_replay import InputFormatComparison
from app.contextual.prompts import DEFAULT_PROMPT_VERSION, PromptVersion, resolve_prompt
from app.contextual.replay import GenerationBaseline
from app.contextual.profiles import ExecutionProfileId
from app.enrichment.agent import AgentSettings
from Evaluation.tracks.contextual.span_inputs import prepare, prepare_batch, audit_batch, structural_candidates
from test_contextual_profiles import legacy_archive


class ContextualInputTests(unittest.IsolatedAsyncioTestCase):
    def test_unicode_crlf_and_combining_marks_are_sliced_without_normalization(self) -> None:
        text = "앞😀\r\n가\u0301. 뒤"
        original = {"places": [], "sources": [{"source_id": "s", "text": text}],
                    "spans": [{"source_id": "s", "start": 1, "end": 7}]}
        before = deepcopy(original)
        result = explicit_chunks(original)
        self.assertEqual(result["spans"][0]["chunk_text"], "😀\r\n가\u0301.")
        self.assertEqual(original, before)
        for start, end in ((True, 3), (-1, 3), (1, len(text) + 1), (3, 3)):
            invalid = deepcopy(original)
            invalid["spans"][0].update(start=start, end=end)
            with self.assertRaises(ValueError):
                explicit_chunks(invalid)
        result["spans"][0]["chunk_text"] = "다른 원문"
        with self.assertRaises(ValueError):
            explicit_chunks(result)

    async def explicit_record(self, root: Path) -> tuple[GenerationBaseline, Path]:
        original = legacy_archive(root / "original")
        legacy = GenerationBaseline.load(original, profile_id=ExecutionProfileId.V1_LOCAL)
        raw = json.loads(original.with_name("raw_response.json").read_text())
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))) as client:
            v4 = await collect_bundle(legacy.bundle, legacy.settings("test-only", 30), root / "v4", client,
                prompt_version=PromptVersion.V4, prepared_request=legacy.candidate_request(PromptVersion.V4),
                request_profile_id=legacy.request_profile_id)
            baseline = GenerationBaseline.load(v4)
            comparison = InputFormatComparison(baseline)
            request = comparison.candidate_request(PromptVersion.V4)
            result = await collect_bundle(
                baseline.bundle, baseline.settings("test-only", 30), root / "explicit", client,
                prompt_version=PromptVersion.V4, prepared_request=request,
                request_profile_id=baseline.request_profile_id, input_version=InputVersion.EXPLICIT)
        return baseline, result

    async def test_only_span_text_changes_and_prompt_only_guard_stays_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline, result = await self.explicit_record(Path(directory))
            request = json.loads(result.with_name("request.json").read_text())
            comparison = InputFormatComparison(baseline)
            comparison.verify_request(request)
            self.assertEqual([key for key in request if request[key] != baseline.request[key]], ["input"])
            with self.assertRaisesRegex(ValueError, "instructions only"):
                baseline.verify_request(request)
            for field, value in (("instructions", "바뀐 지시문"), ("max_output_tokens", 1),
                                 ("effort", "high"), ("response_format", {})):
                with self.assertRaises(ValueError):
                    comparison.verify_request({**request, field: value})
            with self.assertRaises(ValueError):
                comparison.candidate_request(PromptVersion.V5)
            report_path = comparison.write_report(result, output_directory=Path(directory) / "report")
            self.assertEqual(comparison.write_report(result, output_directory=report_path.parent), report_path)
            report = json.loads(report_path.read_text())
            self.assertEqual(report["comparison_kind"], "input-format-only")
            self.assertTrue(report["actual_model_match"])
            self.assertTrue(report["validation_versions_match"])
            self.assertFalse(report["instructions_changed"])

    def test_old_validation_cannot_be_labelled_an_input_only_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = legacy_archive(Path(directory))
            baseline = GenerationBaseline.load(original, profile_id=ExecutionProfileId.V1_LOCAL)
            with self.assertRaisesRegex(ValueError, "무료 재검증"):
                InputFormatComparison(baseline)
            with self.assertRaisesRegex(ValueError, "명시적 청크 입력"):
                baseline.candidate_request(PromptVersion.V5)

    async def test_record_reload_and_free_revalidation_preserve_new_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, result = await self.explicit_record(root)
            original_files = {path: path.read_bytes() for path in result.parent.iterdir() if path.is_file()}
            _, chunks, record = load_record(result)
            self.assertTrue(chunks)
            self.assertEqual(record["input_version"], InputVersion.EXPLICIT)
            replayed = revalidate_record(result, root / "revalidated")
            _, _, replay = load_record(replayed)
            self.assertEqual(replay["input_version"], InputVersion.EXPLICIT)
            self.assertEqual(replay["api_calls"], 0)
            self.assertEqual(original_files, {path: path.read_bytes() for path in original_files})
            bad = json.loads(result.with_name("request.json").read_text())
            bad_input = json.loads(bad["input"])
            bad_input["spans"][0]["chunk_text"] = "인접 구간을 넣은 변조"
            bad["input"] = json.dumps(bad_input, ensure_ascii=False)
            result.with_name("request.json").write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_record(result)
            self.assertTrue(baseline.bundle.sources)

    def test_v5_requires_explicit_input_and_old_default_payload_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = legacy_archive(Path(directory))
            baseline = GenerationBaseline.load(original, profile_id=ExecutionProfileId.V1_LOCAL)
            self.assertEqual(DEFAULT_PROMPT_VERSION, PromptVersion.V2)
            settings = AgentSettings(model="perplexity/sonar", preset=None)
            old = request_payload(baseline.bundle.places, baseline.bundle.sources, settings, prompt_version=PromptVersion.V4)
            self.assertNotIn("chunk_text", json.loads(old["input"])["spans"][0])
            with self.assertRaisesRegex(ValueError, "source-explicit-chunks-v2"):
                request_payload(baseline.bundle.places, baseline.bundle.sources, settings, prompt_version=PromptVersion.V5)
            new = request_payload(baseline.bundle.places, baseline.bundle.sources, settings,
                                  prompt_version=PromptVersion.V5, input_version=InputVersion.EXPLICIT)
            self.assertIn("chunk_text", json.loads(new["input"])["spans"][0])
            self.assertIn("Read the supplied span.chunk_text", new["instructions"])
            self.assertIn("counting Unicode codepoints", resolve_prompt(PromptVersion.V4).instructions)
            self.assertNotIn("counting Unicode codepoints", new["instructions"])

    async def test_explicit_input_can_then_be_a_fixed_input_v5_prompt_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, explicit = await self.explicit_record(root)
            baseline = GenerationBaseline.load(explicit)
            payload = baseline.candidate_request(PromptVersion.V5)
            self.assertEqual(payload["input"], baseline.request["input"])
            raw = json.loads(explicit.with_name("raw_response.json").read_text())
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))) as client:
                candidate = await collect_bundle(baseline.bundle, baseline.settings("test-only", 30), root / "v5", client,
                    prompt_version=PromptVersion.V5, prepared_request=payload, request_profile_id=baseline.request_profile_id,
                    input_version=InputVersion.EXPLICIT)
            load_record(candidate)
            baseline.write_report(candidate, output_directory=root / "reports")

    async def test_cli_and_candidate_plan_need_no_key_client_or_ssl_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = legacy_archive(root / "original")
            baseline = GenerationBaseline.load(original, profile_id=ExecutionProfileId.V1_LOCAL)
            raw = json.loads(original.with_name("raw_response.json").read_text())
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))) as client:
                v4 = await collect_bundle(baseline.bundle, baseline.settings("test-only", 30), root / "v4", client,
                    prompt_version=PromptVersion.V4, prepared_request=baseline.candidate_request(PromptVersion.V4),
                    request_profile_id=baseline.request_profile_id)
            args = argparse.Namespace(command="generate", baseline_record=v4, baseline_profile=None,
                preset=None, model=None, timeout=30, prompt_version=PromptVersion.V4,
                input_version=InputVersion.EXPLICIT, execute=False, refresh=False, output=root / "planned",
                comparison_output=root / "reports")
            with (patch.dict("os.environ", {"SSL_CERT_FILE": str(root / "missing")}, clear=True),
                  patch("app.contextual.cli.httpx.AsyncClient", side_effect=AssertionError("호출 금지")),
                  redirect_stdout(io.StringIO())):
                self.assertEqual(await run(args), 0)
                plan = prepare(v4, root / "candidate-plan")
                summary_path = root / "generation-summary.json"
                summary_path.write_text(json.dumps({"comparison_complete": True,
                    "results": [{"id": "P01", "candidate_record": str(v4)}]}), encoding="utf-8")
                batch = prepare_batch(summary_path, root / "batch")
                audit = audit_batch(batch)
            summary = json.loads(plan.read_text())
            self.assertEqual(summary["api_calls"], 0)
            self.assertFalse(summary["split_candidates_applied"])
            self.assertEqual(summary["original_spans"], summary["explicit_spans"])
            self.assertEqual(audit["original_files_verified_unchanged"], 4)
            self.assertTrue(audit["input_only_verified"])
            candidate = batch.parent / "P01" / "split-candidates.json"
            candidate.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "후보"):
                audit_batch(batch)
            with self.assertRaises(ValueError):
                prepare(v4, plan.parent)

    def test_split_candidates_keep_exact_source_and_do_not_inherit_place_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = legacy_archive(Path(directory))
            baseline = GenerationBaseline.load(original, profile_id=ExecutionProfileId.V1_LOCAL)
            source = baseline.bundle.sources[0]
            source = type(source)(source.source_id, source.source_type, source.title,
                "가공원 주차는 무료다.\r\n...\r\n나공원에서 경치를 봤다.\r\n\r\n**가공원 주차장**\r\n주소😀", source.metadata)
            candidates = structural_candidates(source)
            self.assertGreater(len(candidates), 1)
            self.assertEqual("".join(item["chunk_text"] for item in candidates), source.text)
            parking = next(item for item in candidates if "무료" in item["chunk_text"])
            self.assertNotIn("경치", parking["chunk_text"])
            for item in candidates:
                self.assertEqual(item["source_version"], source.source_version)
                self.assertFalse(item["indexable"])
                self.assertNotIn("place_refs", item)
                self.assertNotIn("context_text", item)


if __name__ == "__main__":
    unittest.main()
