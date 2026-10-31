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
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from jsonschema import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contextual.agent import parse_chunks
from app.contextual.artifacts import collect_bundle, load_record, revalidate_record, request_fingerprint
from app.contextual.cli import run
from app.contextual.prompts import PromptVersion, resolve_prompt
from app.contextual.replay import GenerationBaseline, revalidate_batch
from app.contextual.repository import apply_bundle
from app.contextual.validation import ValidationVersion
from test_contextual_chunks import SETTINGS, bundle, response_for
from test_contextual_profiles import PROFILE_ID, legacy_archive


def set_roles(raw: dict, index: int, roles: list[str]) -> dict:
    document = json.loads(raw['output'][0]['content'][0]['text'])
    chunk = document['chunks'][index]
    chunk['place_refs'] = [{'place_id': 394 + offset, 'role': role} for offset, role in enumerate(roles)]
    chunk['entities'] = [{'name': f'장소 {reference["place_id"]}', **reference} for reference in chunk['place_refs']]
    raw['output'][0]['content'][0]['text'] = json.dumps(document, ensure_ascii=False)
    return raw


class SubjectFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_mixed_roles_are_preserved_and_only_subject_chunks_are_indexable_for_all_prompts(self) -> None:
        value = bundle(3)
        raw = set_roles(response_for(value), 1, ['mentioned', 'view_target'])
        set_roles(raw, 2, [])
        before = deepcopy(raw)
        for version in PromptVersion:
            with self.subTest(prompt=version), tempfile.TemporaryDirectory() as directory:
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=raw))) as http:
                    path = await collect_bundle(value, SETTINGS, Path(directory), http, prompt_version=version)
                _, chunks, record = load_record(path)
                self.assertEqual(len(chunks), 1)
                self.assertEqual(len(record['excluded_chunks']), 2)
                mentioned, unattributed = record['excluded_chunks']
                self.assertEqual(mentioned['exclusion_reason'], 'no_subject')
                self.assertEqual([reference['role'] for reference in mentioned['place_refs']], ['mentioned', 'view_target'])
                self.assertEqual(mentioned['chunk_text'], value.sources[1].text)
                self.assertTrue(mentioned['context_text'])
                self.assertEqual(unattributed['exclusion_reason'], 'unattributed')
                self.assertEqual(json.loads(path.with_name('raw_response.json').read_text(encoding='utf-8')), before)
                self.assertEqual(record['validation_version'], ValidationVersion.SUBJECT_ONLY)
                self.assertEqual(chunks[0].generation['validation_version'], ValidationVersion.SUBJECT_ONLY)
                changed = {**record, 'excluded_chunks': []}
                path.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Excluded chunks'):
                    load_record(path)
        self.assertEqual(raw, before)

    def test_legacy_validation_is_unchanged_and_invalid_non_subject_chunks_still_fail(self) -> None:
        value = bundle()
        raw = set_roles(response_for(value), 0, ['mentioned'])
        for version in (PromptVersion.V1, PromptVersion.V2):
            with self.assertRaisesRegex(ValueError, 'at least one subject'):
                parse_chunks(raw, value.places, value.sources, prompt_version=version)
            self.assertEqual(parse_chunks(raw, value.places, value.sources, prompt_version=version,
                                          validation_version=ValidationVersion.SUBJECT_ONLY), [])
        mutations = {
            'unknown_place': lambda chunk: chunk['place_refs'][0].update(place_id=999),
            'unknown_entity': lambda chunk: chunk['entities'][0].update(place_id=999),
            'wrong_entity_role': lambda chunk: chunk['entities'][0].update(role='subject'),
            'bad_offset': lambda chunk: chunk.update(end=chunk['end'] + 1),
            'duplicate_reference': lambda chunk: chunk['place_refs'].append(deepcopy(chunk['place_refs'][0])),
            'blank_context': lambda chunk: chunk.update(context_text=' '),
            'invalid_role': lambda chunk: chunk['place_refs'][0].update(role='invalid'),
            'empty_refs_with_entities': lambda chunk: chunk.update(place_refs=[]),
        }
        for name, mutate in mutations.items():
            for version in (PromptVersion.V1, PromptVersion.V2):
                with self.subTest(mutation=name, prompt=version):
                    invalid = deepcopy(raw)
                    document = json.loads(invalid['output'][0]['content'][0]['text'])
                    mutate(document['chunks'][0])
                    invalid['output'][0]['content'][0]['text'] = json.dumps(document)
                    with self.assertRaises((ValueError, ValidationError)):
                        parse_chunks(invalid, value.places, value.sources, prompt_version=version,
                                     validation_version=ValidationVersion.SUBJECT_ONLY)

    async def test_zero_subject_is_completed_and_apply_never_acquires_database(self) -> None:
        value = bundle()
        raw = set_roles(response_for(value), 0, ['mentioned', 'view_target'])
        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=raw))) as http:
                path = await collect_bundle(value, SETTINGS, Path(directory), http)
            _, chunks, record = load_record(path)
            self.assertEqual(record['status'], 'COLLECTED')
            self.assertEqual(chunks, [])
            self.assertEqual(len(record['excluded_chunks']), 1)
            pool = MagicMock()
            pool.acquire.side_effect = AssertionError('색인 후보가 없으면 DB를 변경할 수 없다')
            self.assertEqual(await apply_bundle(pool, path), 'NO_INDEXABLE_CHUNKS')
            pool.acquire.assert_not_called()

    async def test_mentions_do_not_queue_reindex_or_replace_other_place_bundles(self) -> None:
        value = bundle()
        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(value)))) as http:
                path = await collect_bundle(value, SETTINGS, Path(directory), http)
            connection = AsyncMock()
            connection.fetchrow.side_effect = [{**place.to_dict(), 'document_status': 'READY', 'source_version': 1,
                                               'latest_seen_version': 1} for place in value.places]
            connection.fetchval.return_value = 1
            connection.execute.return_value = 'INSERT 0 1'
            transaction = MagicMock()
            transaction.__aenter__ = AsyncMock()
            transaction.__aexit__ = AsyncMock(return_value=False)
            connection.transaction = MagicMock(return_value=transaction)
            pool = MagicMock()
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            self.assertEqual(await apply_bundle(pool, path), 'REINDEX_QUEUED')
            bundles = [call.args for call in connection.execute.await_args_list
                       if 'INSERT INTO retrieval_chunk_bundles' in call.args[0]]
            jobs = [call.args for call in connection.execute.await_args_list if 'INSERT INTO place_index_jobs' in call.args[0]]
            self.assertEqual([args[2] for args in bundles], [394])
            self.assertEqual([args[3] for args in jobs], [394])

    async def test_revalidate_preserves_original_bytes_without_http_and_uses_saved_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = legacy_archive(root / 'original')
            raw_path = original.with_name('raw_response.json')
            raw = json.loads(raw_path.read_text(encoding='utf-8'))
            document = json.loads(raw['output'][0]['content'][0]['text'])
            chunk = document['chunks'][0]
            chunk['place_refs'][0]['role'] = 'mentioned'
            chunk['entities'][0]['role'] = 'mentioned'
            raw['output'][0]['content'][0]['text'] = json.dumps(document, ensure_ascii=False)
            raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
            prior = json.loads(original.read_text(encoding='utf-8'))
            original.write_text(json.dumps({key: prior[key] for key in ('schema_version', 'request_hash', 'prompt_version')}
                                           | {'status': 'FAILED', 'error_type': 'ValueError'}), encoding='utf-8')
            before = {path.name: path.read_bytes() for path in original.parent.iterdir()}
            args = argparse.Namespace(command='revalidate', record=original, output=root / 'new', baseline_profile=PROFILE_ID)
            stdout = io.StringIO()
            with patch('httpx.AsyncClient', side_effect=AssertionError('재검증에는 HTTP가 필요 없다')), redirect_stdout(stdout):
                self.assertEqual(await run(args), 0)
            result = Path(json.loads(stdout.getvalue())['record'])
            _, chunks, record = load_record(result)
            self.assertEqual(chunks, [])
            self.assertEqual(record['api_calls'], 0)
            self.assertNotIn('usage', record)
            self.assertEqual(record['excluded_chunks'][0]['place_refs'][0]['role'], 'mentioned')
            self.assertNotEqual(record['request_hash'], prior['request_hash'])
            self.assertEqual(before, {path.name: path.read_bytes() for path in original.parent.iterdir()})
            for name in ('request.json', 'sources.json', 'raw_response.json'):
                self.assertEqual(result.with_name(name).read_bytes(), before[name])
            reusable = GenerationBaseline.load(result)
            def unexpected(request: httpx.Request) -> httpx.Response:
                raise AssertionError('재검증 결과는 캐시로 재사용해야 한다')
            async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
                cached = await collect_bundle(reusable.bundle, reusable.settings('test-only', 60), root / 'new', http,
                                              prompt_version=PromptVersion.V1, prepared_request=reusable.request,
                                              request_profile_id=PROFILE_ID)
            self.assertEqual(cached, result)
            chunk['entities'][0]['name'] = '저장 스키마가 허용하지 않는 이름'
            raw['output'][0]['content'][0]['text'] = json.dumps(document)
            raw_path.write_text(json.dumps(raw), encoding='utf-8')
            with self.assertRaises(ValidationError):
                revalidate_record(original, root / 'rejected', baseline_profile=PROFILE_ID)
            self.assertFalse((root / 'rejected').exists())

    async def test_comparison_reports_same_validation_only_after_both_sides_are_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = legacy_archive(root / 'original')
            baseline = GenerationBaseline.load(original, profile_id=PROFILE_ID)
            original_report = baseline.write_report(original)
            original_report_bytes = original_report.read_bytes()
            self.assertNotIn('validation_versions_match', json.loads(original_report_bytes))
            self.assertEqual(baseline.write_report(original).read_bytes(), original_report_bytes)
            request = baseline.candidate_request(PromptVersion.V2)
            raw = json.loads(original.with_name('raw_response.json').read_text(encoding='utf-8'))
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda query: httpx.Response(200, json=raw))) as http:
                candidate = await collect_bundle(baseline.bundle, baseline.settings('test-only', 60), root / 'new', http,
                                                 prompt_version=PromptVersion.V2, prepared_request=request,
                                                 request_profile_id=PROFILE_ID)
            report = json.loads(baseline.write_report(candidate).read_text(encoding='utf-8'))
            self.assertFalse(report['validation_versions_match'])
            revised_baseline = GenerationBaseline.load(revalidate_record(original, root / 'new', baseline_profile=PROFILE_ID))
            report = json.loads(revised_baseline.write_report(candidate).read_text(encoding='utf-8'))
            self.assertTrue(report['validation_versions_match'])
            self.assertTrue(report['input_and_settings_match'])
            self.assertTrue(report['actual_model_match'])
            self.assertFalse(report['semantic_quality_evaluated'])

    def test_batch_uses_first_saved_response_and_revalidates_both_sides_without_http(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = legacy_archive(root / 'original')
            baseline = GenerationBaseline.load(original, profile_id=PROFILE_ID)
            payload = baseline.candidate_request(PromptVersion.V2)
            original_raw = json.loads(original.with_name('raw_response.json').read_text(encoding='utf-8'))
            for run_name, role, created in (('first', 'mentioned', '2026-10-30T01:00:00Z'),
                                            ('retry', 'subject', '2026-10-30T02:00:00Z')):
                run_dir = root / run_name
                run_dir.mkdir()
                raw = deepcopy(original_raw)
                document = json.loads(raw['output'][0]['content'][0]['text'])
                document['chunks'][0]['place_refs'][0]['role'] = role
                document['chunks'][0]['entities'][0]['role'] = role
                raw['output'][0]['content'][0]['text'] = json.dumps(document)
                run_dir.joinpath('request.json').write_text(json.dumps(payload), encoding='utf-8')
                run_dir.joinpath('sources.json').write_bytes(original.with_name('sources.json').read_bytes())
                run_dir.joinpath('raw_response.json').write_text(json.dumps(raw), encoding='utf-8')
                record = {'schema_version': 1, 'request_hash': request_fingerprint(payload, PromptVersion.V2, PROFILE_ID),
                          'prompt_version': PromptVersion.V2.value, 'request_profile_id': PROFILE_ID,
                          'created_at': created, 'status': 'FAILED', 'error_type': 'ValueError'}
                if role == 'subject':
                    record.update(status='COLLECTED', actual_model=raw['model'],
                                  chunks=[chunk.to_dict() for chunk in parse_chunks(
                                      raw, baseline.bundle.places, baseline.bundle.sources,
                                      prompt_version=PromptVersion.V2, request_profile_id=PROFILE_ID)])
                    record.pop('error_type')
                path = run_dir / 'record.json'
                path.write_text(json.dumps(record), encoding='utf-8')
                baseline.write_report(path)
            before = {path: path.read_bytes() for path in root.rglob('*.json')}
            stray = root / 'unrelated'
            stray.mkdir()
            stray_record = {'schema_version': 1, 'prompt_version': PromptVersion.V1.value,
                            'request_hash': 'unrelated-request', 'status': 'FAILED', 'error_type': 'ValueError'}
            stray.joinpath('record.json').write_text(json.dumps(stray_record), encoding='utf-8')
            stray.joinpath('raw_response.json').write_text('{}', encoding='utf-8')
            with patch('httpx.AsyncClient', side_effect=AssertionError('일괄 재검증은 API를 호출하지 않는다')):
                report_path = revalidate_batch(root, root / 'derived', baseline_profile=PROFILE_ID, paired_only=True)
            report = json.loads(report_path.read_text(encoding='utf-8'))
            self.assertEqual(report['api_calls'], 0)
            self.assertEqual(report['failed'], 0)
            self.assertEqual(len(report['records']), 2)
            self.assertEqual(len(report['comparisons']), 1)
            self.assertEqual(report['out_of_scope_request_hashes'], ['unrelated-request'])
            candidate = next(item for item in report['records'] if item['prompt_version'] == PromptVersion.V2)
            self.assertEqual(Path(candidate['source_record']).parent.name, 'first')
            self.assertEqual(candidate['preserved_response_runs'], 2)
            self.assertEqual(candidate['indexable_chunks'], 0)
            self.assertEqual(candidate['excluded_chunks'], 1)
            comparison = json.loads(Path(report['comparisons'][0]).read_text(encoding='utf-8'))
            self.assertTrue(comparison['validation_versions_match'])
            self.assertTrue(comparison['input_and_settings_match'])
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_prompt_clarification_has_a_separate_version(self) -> None:
        clarified = resolve_prompt(PromptVersion.V3)
        self.assertIn('References containing only mentioned or view_target are valid', clarified.instructions)
        self.assertIn('A clear mention alone is not unclear attribution', clarified.instructions)
        self.assertNotEqual(clarified.instructions, resolve_prompt(PromptVersion.V2).instructions)


if __name__ == '__main__':
    unittest.main()
