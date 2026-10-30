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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contextual.agent import parse_chunks, request_payload
from app.contextual.artifacts import SourceBundle, collect_bundle, load_record, request_fingerprint
from app.contextual.cli import run
from app.contextual.profiles import ExecutionProfileId, resolve_execution_profile
from app.contextual.prompts import PromptVersion, resolve_prompt
from app.contextual.replay import GenerationBaseline
from app.enrichment.artifacts import write_json
from app.enrichment.contracts import ExistingPlace

PROFILE_ID = ExecutionProfileId.V1_LOCAL.value


def legacy_archive(root: Path) -> Path:
    """Fictional sources, with the real local profile's schema and unmodified legacy format."""
    profile = resolve_execution_profile(PROFILE_ID)
    properties = profile.request_settings['response_format']['json_schema']['schema']['properties']['chunks']['items']['properties']
    allowed_name = properties['entities']['items']['properties']['name']['enum'][0]
    place = ExistingPlace(394, allowed_name)
    bundle = SourceBundle.from_mapping({
        'places': [place.to_dict()],
        'sources': [{'source_type': 'review', 'title': '합성 테스트 자료',
                     'text': '실제 방문 후기가 아닌 테스트 문장입니다.',
                     'metadata': {'source_url': 'https://example.org/synthetic', 'capture_scope': 'excerpt'}}],
    })
    request = deepcopy(profile.request_settings)
    source = bundle.sources[0]
    document = {**bundle.to_dict(), 'spans': [{'source_id': source.source_id, 'start': 0, 'end': len(source.text)}]}
    # Noncanonical whitespace/escaping exposes accidental input reconstruction on replay.
    request['input'] = json.dumps(document, ensure_ascii=True, indent=3) + '\n'
    response = {'id': 'mock-local', 'model': request['model'], 'status': 'completed', 'output': [
        {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'chunks': [{
            **document['spans'][0], 'context_text': '해당 장소와 연결된 합성 테스트 문장이다.',
            'place_refs': [{'place_id': place.place_id, 'role': 'subject'}],
            'entities': [{'name': place.name, 'place_id': place.place_id, 'role': 'subject'}],
            'hypothetical_questions': [],
        }]}, ensure_ascii=False)}]},
    ]}
    chunks = parse_chunks(response, bundle.places, bundle.sources, prompt_version=PromptVersion.V1)
    write_json(root / 'request.json', request)
    write_json(root / 'sources.json', bundle.to_dict())
    write_json(root / 'raw_response.json', response)
    write_json(root / 'record.json', {
        'schema_version': 1, 'prompt_version': PromptVersion.V1.value, 'status': 'COLLECTED',
        'request_hash': request_fingerprint(request, PromptVersion.V1),
        'chunks': [chunk.to_dict() for chunk in chunks], 'actual_model': response['model'],
    })
    return root / 'record.json'


class ContextualProfileTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_profile_is_explicit_and_originals_are_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = legacy_archive(Path(directory))
            before = {path: path.read_bytes() for path in record.parent.iterdir()}
            with self.assertRaisesRegex(ValueError, 'archive changed'):
                GenerationBaseline.load(record)
            baseline = GenerationBaseline.load(record, profile_id=PROFILE_ID)
            self.assertEqual(baseline.request['model'], 'perplexity/sonar')
            self.assertEqual(baseline.request['effort'], 'fast')
            self.assertEqual(baseline.request['max_output_tokens'], 8192)
            self.assertNotIn('request_profile_id', baseline.record)
            self.assertEqual({path: path.read_bytes() for path in record.parent.iterdir()}, before)
            with self.assertRaisesRegex(ValueError, 'Unsupported contextual execution profile'):
                GenerationBaseline.load(record, profile_id='v1_local_unregistered')

    def test_profile_rejects_changed_settings_even_with_recomputed_request_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = legacy_archive(Path(directory))
            original_request = json.loads(record.with_name('request.json').read_text())
            original_record = json.loads(record.read_text())
            mutations = {
                'instructions': 'different local instructions', 'effort': 'high',
                'model': 'other-model', 'max_output_tokens': 4096, 'tools': [{'type': 'web_search'}],
                'background': True, 'response_format': {}, 'input': '{}',
            }
            for key, replacement in mutations.items():
                with self.subTest(field=key):
                    changed = {**original_request, key: replacement}
                    record.with_name('request.json').write_text(json.dumps(changed), encoding='utf-8')
                    record.write_text(json.dumps({**original_record, 'request_hash': request_fingerprint(changed, PromptVersion.V1)}), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        GenerationBaseline.load(record, profile_id=PROFILE_ID)

    def test_legacy_hash_model_and_saved_chunks_are_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = legacy_archive(Path(directory))
            original = json.loads(record.read_text())
            for key, replacement in (('request_hash', '0' * 64), ('actual_model', 'incorrect-model'), ('chunks', [])):
                with self.subTest(field=key):
                    record.write_text(json.dumps({**original, key: replacement}), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        GenerationBaseline.load(record, profile_id=PROFILE_ID)

    async def test_replay_preserves_exact_input_and_schema_and_new_records_load_from_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = legacy_archive(root / 'original')
            original_bytes = {path: path.read_bytes() for path in original.parent.iterdir()}
            baseline = GenerationBaseline.load(original, profile_id=PROFILE_ID)
            payload = baseline.candidate_request(PromptVersion.V2)
            self.assertEqual([key for key in payload if payload[key] != baseline.request[key]], ['instructions'])
            self.assertEqual(payload['instructions'], resolve_prompt(PromptVersion.V2).instructions)
            settings = baseline.settings('synthetic-secret', 60)
            canonical = request_payload(baseline.bundle.places, baseline.bundle.sources, settings)
            self.assertNotEqual(payload['input'], canonical['input'])
            response = json.loads(original.with_name('raw_response.json').read_text())
            response['id'] = 'mock-new'
            calls: list[httpx.Request] = []

            def handler(request: httpx.Request) -> httpx.Response:
                calls.append(request)
                self.assertEqual(json.loads(request.content), payload)
                return httpx.Response(200, json=response)

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                options = {'prompt_version': PromptVersion.V2, 'prepared_request': payload, 'request_profile_id': PROFILE_ID}
                candidate = await collect_bundle(baseline.bundle, settings, root / 'new', http, **options)
                self.assertEqual(await collect_bundle(baseline.bundle, settings, root / 'new', http, **options), candidate)
                self.assertEqual(len(calls), 1)
                _, chunks, result = load_record(candidate)
                self.assertEqual(result['request_profile_id'], PROFILE_ID)
                self.assertEqual(chunks[0].generation['request_profile_id'], PROFILE_ID)
                report = json.loads(baseline.write_report(candidate).read_text())
                self.assertEqual(json.loads(baseline.write_report(candidate).read_text()), report)
                self.assertTrue(report['actual_model_match'])
                self.assertTrue(report['input_and_settings_match'])
                self.assertTrue(report['instructions_changed'])
                self.assertFalse(report['semantic_quality_evaluated'])
                self.assertNotIn('synthetic-secret', candidate.with_name('request.json').read_text())
                self.assertEqual({path: path.read_bytes() for path in original.parent.iterdir()}, original_bytes)
                result.pop('request_profile_id')
                candidate.write_text(json.dumps(result), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_record(candidate)

    async def test_nonprompt_changes_are_rejected_before_http(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = GenerationBaseline.load(legacy_archive(root / 'old'), profile_id=PROFILE_ID)
            payload = baseline.candidate_request(PromptVersion.V2)
            payload['max_output_tokens'] = 1024

            def unexpected(request: httpx.Request) -> httpx.Response:
                raise AssertionError('Invalid settings must never call the provider')

            async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
                with self.assertRaisesRegex(ValueError, 'execution profile'):
                    await collect_bundle(baseline.bundle, baseline.settings('test', 60), root / 'new', http,
                                         prepared_request=payload, request_profile_id=PROFILE_ID)
            self.assertFalse((root / 'new').exists())

    async def test_saved_schema_rejects_invalid_entity_and_preserves_failed_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = legacy_archive(root / 'old')
            baseline = GenerationBaseline.load(original, profile_id=PROFILE_ID)
            response = json.loads(original.with_name('raw_response.json').read_text())
            content = response['output'][0]['content'][0]
            document = json.loads(content['text'])
            document['chunks'][0]['entities'][0]['name'] = '다른 공원'
            content['text'] = json.dumps(document)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))) as http:
                result = await collect_bundle(baseline.bundle, baseline.settings('test', 60), root / 'new', http,
                                              prepared_request=baseline.candidate_request(PromptVersion.V2), request_profile_id=PROFILE_ID)
            self.assertEqual(json.loads(result.read_text())['status'], 'FAILED')
            self.assertEqual(json.loads(result.with_name('raw_response.json').read_text()), response)
            self.assertFalse(result.parent.parent.joinpath('latest.json').exists())

    async def test_empty_attribution_is_allowed_and_actual_model_change_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = legacy_archive(root / 'old')
            baseline = GenerationBaseline.load(original, profile_id=PROFILE_ID)
            response = json.loads(original.with_name('raw_response.json').read_text())
            response['model'] = 'changed-provider-model'
            content = response['output'][0]['content'][0]
            document = json.loads(content['text'])
            document['chunks'][0].update(place_refs=[], entities=[])
            content['text'] = json.dumps(document)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))) as http:
                result = await collect_bundle(baseline.bundle, baseline.settings('test', 60), root / 'new', http,
                                              prepared_request=baseline.candidate_request(PromptVersion.V2), request_profile_id=PROFILE_ID)
            self.assertEqual(load_record(result)[1], [])
            self.assertEqual(json.loads(result.with_name('raw_response.json').read_text()), response)
            self.assertFalse(json.loads(baseline.write_report(result).read_text())['actual_model_match'])

    async def test_cli_dry_run_needs_no_key_and_ignores_environment_model_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = legacy_archive(root / 'old')
            args = argparse.Namespace(command='generate', baseline_record=original, baseline_profile=PROFILE_ID,
                                      preset=None, model=None, timeout=60, prompt_version=PromptVersion.V2,
                                      execute=False, refresh=False, output=root / 'new')
            stdout = io.StringIO()
            with (
                patch.dict('os.environ', {
                    'PERPLEXITY_AGENT_MODEL': 'unwanted-model',
                    'SSL_CERT_FILE': str(root / 'missing-ca.pem'),
                }, clear=True),
                patch('app.contextual.cli.httpx.AsyncClient',
                      side_effect=AssertionError('Dry run must not create an HTTP client')) as client,
                redirect_stdout(stdout),
            ):
                self.assertEqual(await run(args), 0)
            client.assert_not_called()
            summary = json.loads(stdout.getvalue())
            result = Path(summary['record'])
            self.assertEqual(summary['status'], 'PLANNED')
            self.assertEqual(json.loads(result.with_name('request.json').read_text())['model'], 'perplexity/sonar')
            self.assertIsNone(json.loads(Path(summary['comparison']).read_text())['actual_model_match'])
            args.model = 'another-model'
            with self.assertRaisesRegex(ValueError, 'omit --preset and --model'):
                await run(args)
            args.baseline_record = None
            with self.assertRaisesRegex(ValueError, 'requires --baseline-record'):
                await run(args)


if __name__ == '__main__':
    unittest.main()
