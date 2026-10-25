"""Synthetic test records validate the evaluator; they are not model benchmark results."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.build import build, check, reference_data
from common.judge.runner import CRITERIA, JudgeSettings, judge_prompt, score_message, validate_judge_output
from tracks.end_to_end.score import evaluate_record
from common.metrics.ranking import ranking_metrics
from common.runs.runner import evaluate
from common.dataset.io import digest, export_inputs, read_json, read_jsonl, write_jsonl

from common.paths import DEFAULT_DATASET

ROOT = DEFAULT_DATASET


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = read_jsonl(ROOT / 'generated/golden.jsonl')
        cls.index = {case['case_id']: case for case in cls.cases}
        cls.corpus = {place['id']: place for place in read_json(ROOT / 'generated/corpus.json')}
        cls.inputs = {row['case_id']: row for row in export_inputs(cls.cases, cls.corpus)}
        cls.sources = {case['case_id']: case for case in read_jsonl(ROOT / 'source/source_goldenset_v1.3.0.jsonl')}

    def record(self, case: dict) -> dict:
        return {
            'case_id': case['case_id'], 'input_sha256': self.inputs[case['case_id']]['input_sha256'],
            'response': copy.deepcopy(case['reference_envelope']),
            'tool_calls': copy.deepcopy(case['expectations']['tool_call']['required_calls']),
            'primary_result_id': 'synthetic-test-result',
            'tool_results': [{
                'result_id': 'synthetic-test-result', 'status': 'completed',
                'response_type': case['expected_response_type'],
                'llm_summary': {'text': case['reference']},
                'public_data': copy.deepcopy(case['reference_envelope']['data']),
            }],
        }

    def test_200_canonical_references_shared_splits_and_all_five_types(self) -> None:
        report = check(ROOT)
        self.assertEqual(report['case_count'], 200)
        self.assertEqual(report['reference_count'], 200)
        self.assertEqual(report['counts_by_group'], {'plannerLLM': 100, 'managerLLM': 100})
        self.assertEqual(set(report['counts_by_type']), {'PLACES', 'PLAN', 'PLAN_DIFF', 'CLARIFICATION', 'TEXT'})
        self.assertTrue(all(case['reference_envelope']['type'] == case['expected_response_type'] for case in self.cases))

    def test_original_corpus_and_human_review_are_preserved(self) -> None:
        legacy = ROOT.parents[0] / 'v1.3.0'
        for target, source in [('corpus.json', 'corpus.json'), ('snapshot.json', 'snapshot.json'),
                               ('source_goldenset_v1.3.0.jsonl', 'golden.jsonl'),
                               ('source_review_notes.csv', 'review_notes_filled_v1.3.0.csv')]:
            self.assertEqual(digest(ROOT / ('generated' if target == 'corpus.json' else 'source') / ('review_notes.csv' if target == 'source_review_notes.csv' else target)), digest(legacy / source))
        self.assertFalse(read_json(ROOT / 'manifest.json')['new_role_expectations_human_reviewed'])

    def test_export_never_leaks_gold_or_private_memory_to_model(self) -> None:
        for prepared in self.inputs.values():
            encoded = json.dumps(prepared['model_input'], ensure_ascii=False)
            self.assertNotIn('"expectations"', encoded)
            self.assertNotIn('"place_judgments"', encoded)
            self.assertNotIn('"reference_envelope"', encoded)
            self.assertNotIn('"allowed_place_ids"', encoded)
        case = next(case for case in self.cases if case['fixtures'].get('memory_read_mode') == 'tool_recall')
        prepared = self.inputs[case['case_id']]
        self.assertEqual(prepared['model_input']['memory_sources'], [])
        self.assertTrue(prepared['harness_fixtures']['memory_store'])

    def test_type_and_server_data_are_separately_checked(self) -> None:
        case = self.index['PLR-TM-palaces-01']
        record = self.record(case)
        self.assertEqual(evaluate_record(case, record)['metrics']['response_type_accuracy'], 1)
        record['response']['data'][0]['name'] = '모델이 다시 써서 바꾼 이름'
        self.assertEqual(evaluate_record(case, record)['metrics']['server_data_unchanged'], 0)
        record['response']['type'] = 'PLAN'
        scores = evaluate_record(case, record)['metrics']
        self.assertEqual(scores['response_type_accuracy'], 0)
        self.assertEqual(scores['envelope_schema_valid'], 0)

    def test_last_internal_search_cannot_override_primary_plan(self) -> None:
        case = next(case for case in self.cases if case['case_type'] == 'plan_result_primary')
        record = self.record(case)
        record['tool_results'].append({
            'result_id': 'later-search', 'status': 'completed', 'response_type': 'PLACES',
            'llm_summary': {'name': '부가 조회'}, 'public_data': [],
        })
        self.assertEqual(evaluate_record(case, record)['metrics']['server_type_matches_primary_result'], 1)
        record['primary_result_id'] = 'later-search'
        self.assertEqual(evaluate_record(case, record)['metrics']['server_type_matches_primary_result'], 0)

    def test_context_filter_arguments_are_not_just_tool_name_matches(self) -> None:
        case = self.index['PLR-TM-palaces-04']
        record = self.record(case)
        self.assertEqual(evaluate_record(case, record)['metrics']['tool_name_and_hard_args_accuracy'], 1)
        record['tool_calls'][0]['arguments']['exclude_place_ids'] = []
        self.assertEqual(evaluate_record(case, record)['metrics']['tool_name_and_hard_args_accuracy'], 0)

    def test_clarification_uses_field_ids_instead_of_exact_question_wording(self) -> None:
        case = self.index['MGR-TM-churches-05']
        record = self.record(case)
        self.assertEqual(record['tool_calls'][0]['arguments']['missing'], ['reference_place', 'distance_range'])
        self.assertEqual(evaluate_record(case, record)['metrics']['tool_name_and_hard_args_accuracy'], 1)
        record['tool_calls'][0]['arguments']['missing'] = ['origin']
        self.assertEqual(evaluate_record(case, record)['metrics']['tool_name_and_hard_args_accuracy'], 0)

    def test_top_k_hit_differs_from_recall_and_duplicates_do_not_inflate_ndcg(self) -> None:
        scores = ranking_metrics([99, 10], {10: 3, 20: 3, 30: 2})
        self.assertEqual(scores['top_5_accuracy'], 1)
        self.assertAlmostEqual(scores['recall_at_5'], 1 / 3)
        duplicate = ranking_metrics([10, 10, 10], {10: 3})
        self.assertLessEqual(duplicate['ndcg_at_5'], 1)
        self.assertEqual(duplicate['recall_at_5'], 1)

    def test_valid_alternative_selection_and_code_route_are_accepted(self) -> None:
        case = self.index['PLR-PLAN-churches']
        record = self.record(case)
        alternate = copy.deepcopy(case)
        chosen = case['expectations']['plan']['relevant_place_ids'][:2]
        record['tool_calls'][0]['arguments']['place_ids'] = list(reversed(chosen))
        alternate['expectations']['tool_call']['required_calls'] = copy.deepcopy(record['tool_calls'])
        data = reference_data(alternate, self.sources[case['source_case_id']], self.corpus)
        record['response']['data'] = data
        record['tool_results'][0]['public_data'] = copy.deepcopy(data)
        scores = evaluate_record(case, record)['metrics']
        self.assertEqual(scores['selection_ids_valid'], 1)
        self.assertEqual(scores['route_cost_ratio'], 1)
        self.assertEqual(scores['route_time_consistent'], 1)
        self.assertEqual(scores['schedule_within_window'], 1)
        record['response']['data']['stops'][0]['arrivalAt'] = '1900-01-01T00:00:00+09:00'
        self.assertEqual(evaluate_record(case, record)['metrics']['route_time_consistent'], 0)

    def test_candidate_guard_checks_raw_selected_ids(self) -> None:
        case = self.index['PLR-PLAN-palaces']
        record = self.record(case)
        record['tool_calls'][0]['arguments']['place_ids'].append(999999)
        self.assertEqual(evaluate_record(case, record)['metrics']['selection_ids_valid'], 0)

    def test_missing_backend_observation_is_not_state_pass(self) -> None:
        case = next(case for case in self.cases if case['case_type'] == 'plan_replace_preview')
        record = self.record(case)
        self.assertIsNone(evaluate_record(case, record)['metrics']['observed_plan_state_preserved'])
        record['observations'] = {
            'source': 'backend_observation',
            'plan_before': {'version': 3}, 'plan_after': {'version': 4},
        }
        self.assertEqual(evaluate_record(case, record)['metrics']['observed_plan_state_preserved'], 0)

    def test_confirmation_receipt_requires_observed_new_version(self) -> None:
        case = next(case for case in self.cases if case['case_type'].startswith('confirmed_plan_'))
        record = self.record(case)
        metrics = evaluate_record(case, record)['metrics']
        self.assertEqual(metrics['confirmation_precedes_apply'], 1)
        self.assertIsNone(metrics['observed_commit_version_matches'])
        record['observations'] = {
            'source': 'backend_observation',
            'plan_before': {'version': 3}, 'plan_after': {'version': 4},
        }
        self.assertEqual(evaluate_record(case, record)['metrics']['observed_commit_version_matches'], 1)
        record['observations']['plan_after']['version'] = 3
        self.assertEqual(evaluate_record(case, record)['metrics']['observed_commit_version_matches'], 0)

    def test_build_does_not_clear_existing_results_and_view_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'evaluation'
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns('__pycache__', 'tests'))
            marker = Path(directory) / 'runs/retained.txt'
            marker.parent.mkdir(parents=True)
            marker.write_text('previous real result')
            build(target)
            self.assertEqual(marker.read_text(), 'previous real result')
            view = target / 'generated/by_type/PLACES.jsonl'
            view.write_text('')
            with self.assertRaisesRegex(ValueError, 'Generated view differs'):
                check(target)

    def test_wrong_input_hash_is_not_a_valid_model_answer(self) -> None:
        case = self.index['PLR-TM-palaces-01']
        record = self.record(case)
        record['input_sha256'] = 'wrong'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            responses = root / 'responses.jsonl'
            write_jsonl(responses, [record])
            code = asyncio.run(evaluate(
                root=ROOT, group='plannerLLM', cases=[case], responses_path=responses,
                output=root / 'reports', use_judge=False,
                settings=JudgeSettings('gpt-4.1-mini', ''),
            ))
            self.assertEqual(code, 2)
            report = read_json(root / 'reports/summary.json')
            self.assertEqual(report['result_count'], 0)
            self.assertEqual(report['invalid_or_missing'][case['case_id']], 'input_hash_missing_or_mismatch')

    def test_offline_evaluation_reports_partial_coverage_without_fake_zero_answers(self) -> None:
        cases = self.cases[:2]
        record = self.record(cases[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            responses = root / 'synthetic-test-responses.jsonl'
            write_jsonl(responses, [record])
            code = asyncio.run(evaluate(
                root=ROOT, group='plannerLLM', cases=cases, responses_path=responses,
                output=root / 'reports', use_judge=False,
                settings=JudgeSettings('gpt-4.1-mini', ''),
            ))
            self.assertEqual(code, 1)
            report = read_json(root / 'reports/summary.json')
            self.assertEqual(report['status'], 'partial')
            self.assertEqual(report['result_count'], 1)
            self.assertEqual(report['code_metrics_and_gpt_scores']['response_type_accuracy']['evaluated_count'], 1)
            self.assertEqual(report['invalid_or_missing'][cases[1]['case_id']], 'response_missing')
            self.assertEqual(read_jsonl(root / 'reports/scores/results.jsonl')[0]['response'], record['response'])

    def test_authentication_failure_stops_repeated_paid_judge_attempts_but_keeps_code_checks(self) -> None:
        class AuthenticationError(RuntimeError):
            pass

        cases = self.cases[:2]
        fake_client = type('FakeClient', (), {'close': AsyncMock()})()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            responses = root / 'synthetic-test-responses.jsonl'
            write_jsonl(responses, [self.record(case) for case in cases])
            with patch('openai.AsyncOpenAI', return_value=fake_client), patch(
                'common.runs.runner.score_message', new=AsyncMock(side_effect=AuthenticationError('do-not-log-provider-secret')),
            ) as judge:
                code = asyncio.run(evaluate(
                    root=ROOT, group='plannerLLM', cases=cases, responses_path=responses,
                    output=root / 'reports', use_judge=True,
                    settings=JudgeSettings('gpt-4.1-mini', 'unit-test-key'),
                ))
            self.assertEqual(code, 1)
            self.assertEqual(judge.await_count, 1)
            rows = read_jsonl(root / 'reports/scores/results.jsonl')
            self.assertEqual([row['judge_status'] for row in rows], ['failed', 'not_run'])
            self.assertTrue(all('response_type_accuracy' in row['code']['metrics'] for row in rows))
            self.assertNotIn('do-not-log-provider-secret', (root / 'reports/scores/results.jsonl').read_text())

    def test_judge_quotes_cannot_come_from_private_memory(self) -> None:
        case = self.index['PLR-TM-palaces-01']
        record = self.record(case)
        messages, actual, supplied = judge_prompt(case, record, self.inputs[case['case_id']]['model_input'], 'test rubric')
        document = {'judgments': [{
            'criterion': criterion, 'applicable': True, 'score': 3, 'reason': 'synthetic test',
            'output_quote': None, 'source_quote': None,
        } for criterion in CRITERIA]}
        validate_judge_output(document, actual, supplied)
        document['judgments'][0]['source_quote'] = '실제로 전달되지 않은 숨겨진 기억'
        with self.assertRaisesRegex(ValueError, 'exact substring'):
            validate_judge_output(document, actual, supplied)
        self.assertIn('test rubric', messages[0]['content'])

    def test_real_openai_adapter_uses_selected_model_and_md_without_paid_calls(self) -> None:
        import httpx
        from openai import AsyncOpenAI

        case = self.index['PLR-TM-palaces-01']
        record = self.record(case)
        seen = []
        document = {'judgments': [{
            'criterion': criterion, 'applicable': True, 'score': 3,
            'reason': 'mock HTTP adapter test only', 'output_quote': None, 'source_quote': None,
        } for criterion in CRITERIA]}

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            seen.append(payload)
            return httpx.Response(200, json={
                'id': 'mock-test', 'object': 'chat.completion', 'created': 0,
                'model': 'gpt-4.1-mini', 'choices': [{
                    'index': 0, 'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': json.dumps(document)},
                }],
            })

        async def run() -> dict:
            async with AsyncOpenAI(api_key='unit-test-key', http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
                return await score_message(
                    case, record, self.inputs[case['case_id']]['model_input'],
                    'ROLE RUBRIC MARKER', JudgeSettings('gpt-4.1-mini', 'unit-test-key'), client=client,
                )

        result = asyncio.run(run())
        self.assertEqual(result['provider_model'], 'gpt-4.1-mini')
        self.assertEqual(seen[0]['model'], 'gpt-4.1-mini')
        self.assertIn('ROLE RUBRIC MARKER', seen[0]['messages'][0]['content'])
        self.assertEqual(seen[0]['response_format']['type'], 'json_schema')


if __name__ == '__main__':
    unittest.main()
