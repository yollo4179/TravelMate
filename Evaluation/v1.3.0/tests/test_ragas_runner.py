"""Prerequisite, publication, and real Ragas/OpenAI-adapter regression checks."""
from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
import csv
import io
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ragas_support.backend import RagasBackend
from ragas_support.inputs import EvaluationBatch, INPUT_FILES, load_batch
from ragas_support.precheck import build_precheck
from ragas_support.settings import EvaluatorSettings, LLM_METRICS, MetricName, RunMode, RunStatus
from run_ragas_evaluation import run_evaluation, write_json, write_jsonl


class RecordingBackend:
    version = "fixture-backend"

    def __init__(self, *, fail: bool = False, partial: bool = False) -> None:
        self.id_calls = 0
        self.llm_calls = 0
        self.fail = fail
        self.partial = partial

    async def score_ids(self, batch: EvaluationBatch) -> list[dict[str, Any]]:
        self.id_calls += 1
        return [{
            "case_id": sample["case_id"], "strategy_version": version,
            "id_based_context_precision": 0.5, "id_based_context_recall": 1.0,
        } for version, samples in batch.samples_by_version.items() for sample in samples]

    async def score_llm(self, batch: EvaluationBatch, settings: EvaluatorSettings) -> list[dict[str, Any]]:
        self.llm_calls += 1
        if self.fail:
            raise RuntimeError(f"provider error containing {settings.api_key}")
        rows = [{
            "case_id": sample["case_id"], "strategy_version": version,
            **{metric.value: 0.75 for metric in LLM_METRICS},
        } for version, samples in batch.samples_by_version.items() for sample in samples]
        return rows[:1] if self.partial else rows


class RunnerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.settings = EvaluatorSettings("gpt-4.1-mini", "text-embedding-3-small", "test-secret-not-a-real-key")
        with (self.root / 'review_notes_filled_v1.3.0.csv').open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=['case_id', 'place_id', 'relevance', 'review_status'])
            writer.writeheader()
            writer.writerows([
                {'case_id': 'case-1', 'place_id': 378, 'relevance': 3, 'review_status': 'pending_human_review'},
                {'case_id': 'case-1', 'place_id': 380, 'relevance': 0, 'review_status': 'pending_human_review'},
            ])
        for strategy, path in INPUT_FILES.items():
            (self.root / path).parent.mkdir(parents=True)
            write_jsonl(self.root / path, [{
                'case_id': 'case-1', 'strategy_version': strategy.value,
                'user_input': '창경궁을 찾아줘.', 'response': '요청한 장소는 창경궁입니다.',
                'retrieved_context_ids': [378, 999],
                'retrieved_contexts': ['창경궁은 왕실 가족의 생활공간이었다.', '다른 장소 소개'],
                'reference': None, 'execution_status': 'completed', 'condition_coverage': 'complete',
                'ragas_id_metrics_eligible': False, 'ragas_llm_eligible': False,
            }])

    def add_reference(self, text: str = '요청한 장소는 창경궁입니다.') -> None:
        write_jsonl(self.root / 'golden.jsonl', [{'case_id': 'case-1', 'query': '창경궁을 찾아줘.', 'reference': text}])

    def edit_api(self, **changes: Any) -> None:
        for path in INPUT_FILES.values():
            row = json.loads((self.root / path).read_text())
            row.update(changes)
            write_jsonl(self.root / path, [row])

    def run_runner(self, backend: RecordingBackend, mode: RunMode = RunMode.ALL, **options: Any) -> int:
        with redirect_stdout(io.StringIO()):
            return asyncio.run(run_evaluation(
                root=self.root, output=self.root, settings=self.settings, mode=mode, backend=backend, **options,
            ))


class RunnerTests(RunnerFixture):
    def test_missing_reference_does_not_block_faithfulness_inputs_but_blocks_batch(self) -> None:
        report = build_precheck(load_batch(self.root), self.settings)
        self.assertEqual(report['status'], RunStatus.BLOCKED)
        self.assertEqual(report['metrics']['faithfulness']['reasons'], [])
        self.assertFalse(report['metrics']['faithfulness']['reference_required'])
        self.assertTrue(report['metrics']['faithfulness']['deferred_by_batch_policy'])
        self.assertEqual(report['metrics']['answer_correctness']['reasons'], ['missing_reference'])

    def test_missing_key_is_actual_configuration_check_not_fixed_false(self) -> None:
        self.add_reference()
        missing = EvaluatorSettings(self.settings.judge_model, self.settings.embedding_model, '')
        self.assertEqual(build_precheck(load_batch(self.root), missing)['status'], RunStatus.BLOCKED)
        self.assertEqual(build_precheck(load_batch(self.root), self.settings)['status'], RunStatus.READY)
        self.assertNotIn(self.settings.api_key, repr(self.settings))
        self.assertNotIn(self.settings.api_key, json.dumps(self.settings.public_settings()))

    def test_embeddings_are_required_only_for_answer_correctness(self) -> None:
        self.add_reference()
        settings = EvaluatorSettings(self.settings.judge_model, '', self.settings.api_key)
        metrics = build_precheck(load_batch(self.root), settings)['metrics']
        self.assertIn('embedding_evaluator_not_configured', metrics['answer_correctness']['reasons'])
        self.assertEqual(metrics['faithfulness']['reasons'], [])
        self.assertEqual(metrics['context_recall']['reasons'], [])

    def test_missing_response_is_not_a_context_recall_requirement(self) -> None:
        self.add_reference()
        self.edit_api(response=None)
        metrics = build_precheck(load_batch(self.root), self.settings)['metrics']
        self.assertEqual(metrics['context_recall']['reasons'], [])
        self.assertIn('missing_response', metrics['faithfulness']['reasons'])

    def test_id_evaluation_remains_possible_without_context_texts(self) -> None:
        self.add_reference()
        self.edit_api(retrieved_contexts=[])
        batch = load_batch(self.root)
        self.assertEqual(batch.paired_case_count, 1)
        metrics = build_precheck(batch, self.settings)['metrics']
        self.assertEqual(metrics['answer_correctness']['reasons'], [])
        self.assertIn('missing_retrieved_contexts', metrics['faithfulness']['reasons'])
        self.assertEqual(self.run_runner(RecordingBackend(), RunMode.ID), 0)

    def test_precheck_only_makes_no_backend_calls(self) -> None:
        backend = RecordingBackend()
        self.assertEqual(self.run_runner(backend, precheck_only=True), 2)
        self.assertEqual((backend.id_calls, backend.llm_calls), (0, 0))

    def test_id_results_remain_available_when_llm_batch_is_blocked(self) -> None:
        backend = RecordingBackend()
        self.assertEqual(self.run_runner(backend), 2)
        self.assertEqual((backend.id_calls, backend.llm_calls), (1, 0))
        self.assertEqual(len((self.root / 'ragas_results.jsonl').read_text().splitlines()), 2)
        self.assertFalse((self.root / 'ragas_llm_results.jsonl').exists())

    def test_all_three_metrics_are_published_only_after_both_versions_finish(self) -> None:
        self.add_reference()
        before = {path: (self.root / path).read_bytes() for path in INPUT_FILES.values()}
        self.assertEqual(self.run_runner(RecordingBackend()), 0)
        rows = [json.loads(line) for line in (self.root / 'ragas_llm_results.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(all(metric.value in row for metric in LLM_METRICS))
        report = json.loads((self.root / 'ragas_llm_summary.json').read_text())
        self.assertEqual(report['metric_value_count'], 6)
        self.assertEqual({path: (self.root / path).read_bytes() for path in INPUT_FILES.values()}, before)

    def test_provider_failure_does_not_publish_partial_or_leak_key(self) -> None:
        self.add_reference()
        old = '{"prior_run":"preserve"}\n'
        (self.root / 'ragas_llm_results.jsonl').write_text(old)
        self.assertEqual(self.run_runner(RecordingBackend(fail=True), RunMode.LLM), 1)
        self.assertEqual((self.root / 'ragas_llm_results.jsonl').read_text(), old)
        summary = (self.root / 'ragas_llm_summary.json').read_text()
        self.assertNotIn(self.settings.api_key, summary)
        self.assertEqual(json.loads(summary)['score_count'], 0)
        self.assertIsNone(json.loads(summary)['results_file'])

    def test_incomplete_returned_batch_is_not_published(self) -> None:
        self.add_reference()
        self.assertEqual(self.run_runner(RecordingBackend(partial=True), RunMode.LLM), 1)
        self.assertFalse((self.root / 'ragas_llm_results.jsonl').exists())

    def test_prior_eligibility_flags_are_recomputed_and_unjudged_stays_separate(self) -> None:
        batch = load_batch(self.root)
        self.assertEqual(batch.paired_case_count, 1)
        for samples in batch.samples_by_version.values():
            self.assertEqual(samples[0]['judged_retrieved_context_ids'], [378])
            self.assertEqual(samples[0]['unjudged_retrieved_context_ids'], [999])

    def test_duplicate_ids_and_duplicate_cases_are_rejected(self) -> None:
        self.edit_api(retrieved_context_ids=[378, 378])
        with self.assertRaisesRegex(ValueError, 'duplicate IDs'):
            load_batch(self.root)
        self.edit_api(retrieved_context_ids=[378, 999])
        path = self.root / next(iter(INPUT_FILES.values()))
        content = path.read_text()
        path.write_text(content + content)
        with self.assertRaisesRegex(ValueError, 'duplicate API case IDs'):
            load_batch(self.root)

    def test_conflicting_reference_and_changed_query_are_rejected(self) -> None:
        self.add_reference()
        self.edit_api(reference='원본과 다른 기대 답변')
        with self.assertRaisesRegex(ValueError, 'conflicting references'):
            load_batch(self.root)
        self.edit_api(reference=None, user_input='다른 질문')
        with self.assertRaisesRegex(ValueError, 'differs from golden query'):
            load_batch(self.root)

    def test_wrong_input_strategy_is_rejected(self) -> None:
        self.edit_api(strategy_version='wrong')
        with self.assertRaisesRegex(ValueError, 'strategy version'):
            load_batch(self.root)

    def test_configuration_loads_agreed_models_without_serializing_key(self) -> None:
        settings = EvaluatorSettings.load(ROOT / 'ragas_config.json', {'OPENAI_API_KEY': self.settings.api_key})
        self.assertEqual(settings.judge_model, 'gpt-4.1-mini')
        self.assertEqual(settings.embedding_model, 'text-embedding-3-small')


@unittest.skipUnless(importlib.util.find_spec('ragas'), 'Install requirements-evaluation.txt for real Ragas integration checks')
class RagasIntegrationTests(RunnerFixture):
    def test_real_ragas_id_metric_uses_csv_ids_without_openai(self) -> None:
        with patch.dict(os.environ, {'RAGAS_DO_NOT_TRACK': 'true'}):
            rows = asyncio.run(RagasBackend().score_ids(load_batch(self.root)))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['id_based_context_precision'] == 0.5 for row in rows))
        self.assertTrue(all(row['id_based_context_recall'] == 1.0 for row in rows))

    def test_real_llm_metrics_call_openai_chat_and_embedding_adapters(self) -> None:
        import httpx
        from openai import AsyncOpenAI

        self.add_reference()
        requests: list[dict[str, Any]] = []
        fact = '창경궁은 왕실 가족의 생활공간이었다.'
        fixtures = {
            'ClassificationWithReason': {'TP': [{'statement': fact, 'reason': 'fixture match'}], 'FP': [], 'FN': []},
            'NLIStatementOutput': {'statements': [{'statement': fact, 'reason': 'fixture support', 'verdict': 1}]},
            'ContextRecallOutput': {'classifications': [{'statement': fact, 'reason': 'fixture coverage', 'attributed': 1}]},
            'StatementGeneratorOutput': {'statements': [fact]},
        }

        def respond(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            requests.append({'path': request.url.path, 'model': payload['model']})
            self.assertEqual(request.url.host, 'api.openai.com')
            if request.url.path.endswith('/embeddings'):
                return httpx.Response(200, json={
                    'object': 'list', 'model': payload['model'],
                    'data': [{'object': 'embedding', 'index': 0, 'embedding': [1.0, 0.0, 0.0]}],
                    'usage': {'prompt_tokens': 1, 'total_tokens': 1},
                })
            prompt = json.dumps(payload, ensure_ascii=False)
            content = next(value for name, value in fixtures.items() if name in prompt)
            return httpx.Response(200, json={
                'id': 'chat-fixture', 'object': 'chat.completion', 'created': 0, 'model': payload['model'],
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': json.dumps(content)}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
            })

        class MockTransportBackend(RagasBackend):
            def create_client(backend_self, settings: EvaluatorSettings) -> Any:
                return AsyncOpenAI(
                    api_key=settings.api_key, base_url='https://api.openai.com/v1',
                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
                )

        with patch.dict(os.environ, {'RAGAS_DO_NOT_TRACK': 'true'}):
            code = asyncio.run(run_evaluation(
                root=self.root, output=self.root, settings=self.settings,
                mode=RunMode.LLM, backend=MockTransportBackend(),
            ))
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in (self.root / 'ragas_llm_results.jsonl').read_text().splitlines()]
        for row in rows:
            for metric in LLM_METRICS:
                self.assertAlmostEqual(row[metric.value], 1.0)
        self.assertTrue(any(request['model'] == 'gpt-4.1-mini' for request in requests))
        self.assertTrue(any(request['model'] == 'text-embedding-3-small' for request in requests))


if __name__ == '__main__':
    unittest.main()
