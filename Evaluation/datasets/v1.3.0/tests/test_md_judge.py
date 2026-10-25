"""MD rubric inclusion, reference independence and grounded judge outputs."""
from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
import unittest
from typing import Any
from unittest.mock import patch

from test_ragas_runner import ROOT, RunnerFixture
from ragas_support.inputs import INPUT_FILES, load_batch
from ragas_support.judge import JudgeOutputError, MarkdownJudgeBackend, prepare_case, validate_judgments
from ragas_support.settings import EvaluatorSettings, RunMode
from run_ragas_evaluation import run_evaluation, write_json, write_jsonl


class FixtureJudge:
    version = 'fixture-judge'

    def __init__(self, *, bad_quote: bool = False) -> None:
        self.cases: list[dict[str, Any]] = []
        self.rubric = ''
        self.bad_quote = bad_quote

    async def score_rubric(self, cases: list[dict[str, Any]], rubric: str, settings: Any) -> list[dict[str, Any]]:
        self.cases = cases
        self.rubric = rubric
        return [{
            'case_id': case['case_id'], 'strategy_version': case['strategy_version'],
            'judgments': [{
                'place_id': place['place_id'], 'score': 3 if place['place_id'] == '378' else 0,
                'reason': 'fixture only', 'missing_requirements': [],
                'evidence': [{'source_place_id': place['place_id'], 'field': 'name',
                              'quote': '없는 인용' if self.bad_quote else next(source['name'] for source in case['source_places'] if source['place_id'] == place['place_id'])}],
            } for place in case['returned_places']],
        } for case in cases]


class JudgeFixture(RunnerFixture):
    def setUp(self) -> None:
        super().setUp()
        self.conditions = {'region': '서울', 'city': None, 'category': None, 'area': None, 'exclude_place_ids': [], 'conversation': []}
        self.places = [
            {'id': 378, 'name': '창경궁', 'description': '왕실 가족의 생활공간이다.', 'region': '서울', 'city': '종로', 'category': '관광지', 'source_category': '고궁', 'latitude': 37.5, 'longitude': 127.0},
            {'id': 999, 'name': '다른 공원', 'description': '다른 동네의 공원이다.', 'region': '서울', 'city': '종로', 'category': '관광지', 'source_category': '공원', 'latitude': 37.5, 'longitude': 127.0},
        ]
        write_json(self.root / 'corpus.json', self.places)
        self.case = {
            'case_id': 'case-1', 'case_type': 'exact_name', 'query': '창경궁을 찾아줘.',
            'conditions': self.conditions, 'semantic_constraints': [], 'reference': None,
            'judgments': [{'place_id': 378, 'relevance': 3, 'rationale': 'CSV_LABEL_SECRET_SENTINEL'}],
        }
        write_jsonl(self.root / 'golden.jsonl', [self.case])
        returned = [{'placeId': place['id'], **{key: value for key, value in place.items() if key != 'id'}} for place in self.places]
        self.edit_api(response=json.dumps(returned, ensure_ascii=False))
        self.rubric_path = self.root / 'criteria.md'
        self.rubric_path.write_text('# MD_RUBRIC_SENTINEL\n기존 0~3점으로 평가하고 원문을 인용한다.\n')

    def run_judge(self, backend: Any, *, precheck_only: bool = False) -> int:
        with redirect_stdout(io.StringIO()):
            return asyncio.run(run_evaluation(
                root=self.root, output=self.root, settings=self.settings,
                mode=RunMode.JUDGE, precheck_only=precheck_only,
                rubric_path=self.rubric_path, rubric_backend=backend,
            ))


class MarkdownJudgeTests(JudgeFixture):
    def test_null_reference_does_not_block_md_judge_and_md_is_read(self) -> None:
        backend = FixtureJudge()
        self.assertEqual(self.run_judge(backend), 0)
        self.assertEqual(backend.rubric, self.rubric_path.read_text())
        report = json.loads((self.root / 'llm_judge_precheck.json').read_text())
        self.assertFalse(report['reference_required'])
        self.assertFalse(report['embeddings_required'])
        self.assertEqual(report['status'], 'completed')

    def test_csv_scores_are_attached_after_model_call_and_not_in_prompt(self) -> None:
        backend = FixtureJudge()
        self.assertEqual(self.run_judge(backend), 0)
        payload = json.dumps(backend.cases)
        self.assertNotIn('CSV_LABEL_SECRET_SENTINEL', payload)
        self.assertNotIn('relevance', payload)
        self.assertNotIn('reference', payload)
        results = [json.loads(line) for line in (self.root / 'llm_judge_results.jsonl').read_text().splitlines()]
        for result in results:
            self.assertEqual(result['judgments'][0]['csv_relevance'], 3)
            self.assertTrue(result['judgments'][0]['csv_agrees'])
            self.assertIsNone(result['judgments'][1]['csv_relevance'])

    def test_reference_fields_are_not_validated_or_used_in_judge_mode(self) -> None:
        self.case['reference'] = {'not': 'a text reference'}
        write_jsonl(self.root / 'golden.jsonl', [self.case])
        self.edit_api(reference='a different reference')
        self.assertEqual(self.run_judge(FixtureJudge()), 0)

    def test_judge_does_not_require_an_embedding_model(self) -> None:
        self.settings = EvaluatorSettings(self.settings.judge_model, '', self.settings.api_key)
        self.assertEqual(self.run_judge(FixtureJudge()), 0)

    def test_reference_based_reports_and_input_files_are_preserved(self) -> None:
        sentinel = 'previous reference-based report'
        (self.root / 'ragas_llm_precheck.json').write_text(sentinel)
        before = {path: (self.root / path).read_bytes() for path in INPUT_FILES.values()}
        self.assertEqual(self.run_judge(FixtureJudge()), 0)
        self.assertEqual((self.root / 'ragas_llm_precheck.json').read_text(), sentinel)
        self.assertEqual(before, {path: (self.root / path).read_bytes() for path in INPUT_FILES.values()})

    def test_invalid_quote_is_not_published(self) -> None:
        self.assertEqual(self.run_judge(FixtureJudge(bad_quote=True)), 1)
        self.assertFalse((self.root / 'llm_judge_results.jsonl').exists())
        summary = json.loads((self.root / 'llm_judge_summary.json').read_text())
        self.assertEqual(summary['validation_issue'], 'citation_does_not_match_source')

    def test_hard_filter_violation_cannot_receive_positive_score(self) -> None:
        self.case['conditions']['exclude_place_ids'] = [378]
        write_jsonl(self.root / 'golden.jsonl', [self.case])
        self.assertEqual(self.run_judge(FixtureJudge()), 1)
        summary = json.loads((self.root / 'llm_judge_summary.json').read_text())
        self.assertEqual(summary['validation_issue'], 'nonzero_score_violates_hard_filter')

    def test_precheck_does_not_call_judge(self) -> None:
        backend = FixtureJudge()
        self.assertEqual(self.run_judge(backend, precheck_only=True), 0)
        self.assertEqual(backend.cases, [])


@unittest.skipUnless(importlib.util.find_spec('ragas'), 'Install requirements-evaluation.txt')
class MarkdownJudgeIntegrationTests(JudgeFixture):
    def test_openai_prompt_contains_actual_md_without_reference_or_embeddings(self) -> None:
        import httpx
        from openai import AsyncOpenAI

        requests: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            self.assertTrue(request.url.path.endswith('/chat/completions'))
            payload = json.loads(request.content)
            self.assertEqual(payload['model'], 'gpt-4.1-mini')
            rendered = json.dumps(payload, ensure_ascii=False)
            self.assertIn('MD_RUBRIC_SENTINEL', rendered)
            self.assertNotIn('CSV_LABEL_SECRET_SENTINEL', rendered)
            requests.append(request.url.path)
            judgments = [{
                'place_id': str(place['id']), 'score': 3 if place['id'] == 378 else 0,
                'reason': 'fixture', 'missing_requirements': [],
                'evidence': [{'source_place_id': str(place['id']), 'field': 'name', 'quote': place['name']}],
            } for place in self.places]
            return httpx.Response(200, json={
                'id': 'judge-fixture', 'object': 'chat.completion', 'created': 0, 'model': payload['model'],
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': json.dumps({'judgments': judgments})}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
            })

        class MockJudge(MarkdownJudgeBackend):
            def create_client(backend_self, settings: Any) -> Any:
                return AsyncOpenAI(api_key=settings.api_key, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))

        with patch.dict(os.environ, {'RAGAS_DO_NOT_TRACK': 'true'}):
            self.assertEqual(self.run_judge(MockJudge()), 0)
        self.assertEqual(len(requests), 2)


if __name__ == '__main__':
    unittest.main()
