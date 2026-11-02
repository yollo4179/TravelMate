"""유료 생성 전 요청 고정, 중단·재호출 방지, 비용 감사와 키 비공개를 검증한다."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))
from app.contextual.artifacts import collect_bundle
from app.contextual.profiles import ExecutionProfileId
from app.contextual.prompts import PromptVersion
from app.contextual.replay import GenerationBaseline
from Evaluation.tracks.contextual.span_inputs import prepare_batch
from Evaluation.tracks.contextual.span_generation import prepare, generate, audit, export_review, verified_plan, summarize_review
from test_contextual_profiles import legacy_archive


class SpanGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def prepared(self, root: Path, *, pairs: int = 1) -> tuple[Path, Path, dict]:
        original = legacy_archive(root / "legacy")
        baseline = GenerationBaseline.load(original, profile_id=ExecutionProfileId.V1_LOCAL)
        response = json.loads(original.with_name("raw_response.json").read_text())
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))) as client:
            v4 = await collect_bundle(baseline.bundle, baseline.settings("test-only", 30), root / "v4", client,
                prompt_version=PromptVersion.V4, prepared_request=baseline.candidate_request(PromptVersion.V4),
                request_profile_id=baseline.request_profile_id)
        summaries = [{"id": f"P{number:02d}", "candidate_record": str(v4)} for number in range(1, pairs + 1)]
        summary_path = root / "generation-summary.json"
        summary_path.write_text(json.dumps({"comparison_complete": True, "results": summaries}), encoding="utf-8")
        batch = prepare_batch(summary_path, root / "inputs")
        spans = json.loads(json.loads(v4.with_name("request.json").read_text())["input"])["spans"]
        rows = [{"id": f'{pair["id"]}-S{index:02d}', "pair_id": pair["id"], **span}
                for pair in summaries for index, span in enumerate(spans, 1)]
        labels = root / "prepared.json"
        labels.write_text(json.dumps({"rows": rows}), encoding="utf-8")
        plan = prepare(batch, labels, root / "generated")
        key_path = root / "test-key.txt"
        key_path.write_text("pplx-" + "a" * 30, encoding="utf-8")
        response["id"] = "v5-test-response"
        response["usage"] = {"cost": {"currency": "USD", "total_cost": 0.001}}
        return plan, key_path, response

    async def test_exact_request_single_call_audit_and_review_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, key_path, response = await self.prepared(Path(directory))
            planned = verified_plan(plan)
            seen = []

            def handler(request: httpx.Request) -> httpx.Response:
                seen.append(json.loads(request.content))
                return httpx.Response(200, json=response)

            with redirect_stdout(io.StringIO()):
                result = await generate(plan, key_path, transport=httpx.MockTransport(handler))
            self.assertEqual(seen, [planned["pairs"][0]["request"]])
            self.assertTrue(json.loads(result.read_text())["comparison_complete"])
            audited = audit(plan)
            self.assertEqual(audited["api_calls"], 1)
            self.assertEqual(audited["provider_reported_cost_usd"], "0.001")
            self.assertEqual(audited["comparison_kind"], "explicit-input-and-instructions")
            exported = json.loads(export_review(plan).read_text())
            self.assertTrue(exported["rows"])
            self.assertEqual(exported["rows"][0]["v5"]["source_id"], exported["rows"][0]["source_id"])
            review_root = Path(directory) / "review-repository"
            prior = review_root / "Evaluation/tracks/contextual/prompt_v4_review.json"
            prior.parent.mkdir(parents=True)
            prior.write_text(json.dumps({"rows": [{"id": row["id"], "v4": []} for row in exported["rows"]]}), encoding="utf-8")
            annotation = Path(directory) / "review.json"
            review = {"comparison_kind": "explicit-input-and-instructions", "reviewer": "모의 검수",
                "rubric": {}, "rows": [{"id": row["id"], "v5": []} for row in exported["rows"]]}
            annotation.write_text(json.dumps(review), encoding="utf-8")
            with patch("Evaluation.tracks.contextual.span_generation.REPOSITORY", review_root):
                verified = summarize_review(plan, annotation)
                self.assertEqual(verified["reviewed_spans"], len(exported["rows"]))
                self.assertEqual(verified["span_topic_replaced"], {"v4": 0, "v5": 0})
                review["rows"].append(review["rows"][0])
                annotation.write_text(json.dumps(review), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "중복·누락"):
                    summarize_review(plan, annotation)
            with self.assertRaisesRegex(ValueError, "자동 재시도"):
                await generate(plan, key_path, transport=httpx.MockTransport(handler))
            self.assertEqual(len(seen), 1)

    async def test_http_rejection_stops_batch_and_redacts_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, key_path, _ = await self.prepared(Path(directory), pairs=2)
            key = key_path.read_text()
            count = 0

            def handler(_: httpx.Request) -> httpx.Response:
                nonlocal count
                count += 1
                return httpx.Response(403, text=f"denied {key}", headers={"x-request-id": "test-request-id"})

            with redirect_stdout(io.StringIO()):
                result = await generate(plan, key_path, transport=httpx.MockTransport(handler))
            summary = json.loads(result.read_text())
            self.assertEqual(count, 1)
            self.assertFalse(summary["comparison_complete"])
            self.assertEqual(len(summary["results"]), 1)
            diagnostics = list(plan.with_name("http-errors").glob("*.json"))
            self.assertEqual(len(diagnostics), 1)
            self.assertNotIn(key, diagnostics[0].read_text())
            self.assertIn("REDACTED", diagnostics[0].read_text())
            self.assertEqual(json.loads(diagnostics[0].read_text())["request_id"], "test-request-id")

    async def test_plan_tampering_is_rejected_before_key_or_http_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, key_path, _ = await self.prepared(Path(directory))
            document = json.loads(plan.read_text())
            document["pairs"][0]["request"]["max_output_tokens"] = 1
            plan.write_text(json.dumps(document), encoding="utf-8")
            with (patch("Evaluation.tracks.contextual.span_generation.read_api_key", side_effect=AssertionError("키 읽기 금지")),
                  patch("Evaluation.tracks.contextual.span_generation.httpx.AsyncClient", side_effect=AssertionError("클라이언트 생성 금지"))):
                with self.assertRaisesRegex(ValueError, "실행 요청"):
                    await generate(plan, key_path)


if __name__ == "__main__":
    unittest.main()
