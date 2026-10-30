from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.contextual.agent import parse_chunks, request_payload
from app.contextual.artifacts import SourceBundle, collect_bundle, load_record
from app.contextual.contracts import SearchChunk, archive_directory
from app.contextual.pipeline import normalize_source, select_active, split_source, tourapi_chunks
from app.contextual.prompts import PromptVersion
from app.contextual.replay import GenerationBaseline
from app.contextual.repository import apply_bundle, desired_chunks
from app.enrichment.agent import AgentSettings
from app.enrichment.contracts import ExistingPlace
from app.enrichment.repository import ensure_schema
from app.enrichment.evidence import normalize_response

PLACE = ExistingPlace(394, '테스트 공원', description='공식 장소 설명')
MENTIONED = ExistingPlace(395, '조망 다리')
SETTINGS = AgentSettings(preset='sonar-pro', api_key='test-only')


def source(index: int = 0, kind: str = 'review') -> dict:
    return {'source_type': kind, 'title': f'방문 후기 {index}',
            'text': f'평일 {index}시에는 공원 벤치에서 다리가 보였다. 주말에는 혼잡했다.',
            'metadata': {'source_url': f'https://example.org/accounts/{index}', 'capture_scope': 'excerpt'}}


def bundle(count: int = 1) -> SourceBundle:
    return SourceBundle.from_mapping({'places': [PLACE.to_dict(), MENTIONED.to_dict()],
                                     'sources': [source(index) for index in range(count)]})


def response_for(value: SourceBundle, context: str = '공원 방문기에서 평일 조망과 주말 혼잡을 비교하는 부분이다.') -> dict:
    chunks = [{'source_id': item.source_id, 'start': start, 'end': end, 'context_text': context,
               'place_refs': [{'place_id': PLACE.place_id, 'role': 'subject'},
                              {'place_id': MENTIONED.place_id, 'role': 'view_target'}],
               'entities': [{'name': PLACE.name, 'place_id': PLACE.place_id, 'role': 'subject'}],
               'hypothetical_questions': []}
              for item in value.sources for start, end in split_source(item)]
    return {'id': 'mock-context', 'model': 'mock-sonar', 'status': 'completed', 'output': [
        {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'chunks': chunks}, ensure_ascii=False)}]}]}


class ContextualTests(unittest.IsolatedAsyncioTestCase):
    def test_common_sources_preserve_text_offsets_and_context_input(self) -> None:
        for kind in ('tourapi', 'blog_post', 'review', 'web_excerpt'):
            with self.subTest(kind=kind):
                item = normalize_source(source(kind=kind))
                chunk = SearchChunk(item, 0, len(item.text), '짧은 문맥', [{'place_id': 394, 'role': 'subject'}], {'model': 'mock'})
                self.assertEqual(chunk.embedding_text, '짧은 문맥\n\n' + item.text)
                self.assertEqual(chunk.to_dict()['chunk_text'], item.text)
                self.assertEqual(SearchChunk.from_mapping(item, chunk.to_dict()), chunk)
        self.assertEqual(tourapi_chunks(PLACE)[0].chunk_text, PLACE.description)

    def test_stable_global_ids_and_separate_context_revisions(self) -> None:
        original = parse_chunks(response_for(bundle()), bundle().places, bundle().sources)[0]
        regenerated = parse_chunks(response_for(bundle(), '새 문맥'), bundle().places, bundle().sources)[0]
        self.assertEqual(original.chunk_id, regenerated.chunk_id)
        self.assertNotEqual(original.context_version, regenerated.context_version)
        changed = source(); changed['text'] += ' 밤에는 어두웠다.'
        revised = normalize_source(changed)
        self.assertEqual(original.source.source_id, revised.source_id)
        self.assertNotEqual(original.source.source_version, revised.source_version)
        self.assertNotEqual(original.chunk_id, SearchChunk(revised, 0, len(revised.text), '문맥', original.place_refs, {}).chunk_id)

    def test_selection_caps_subjects_not_mentions_without_erasing_originals(self) -> None:
        value = bundle(35)
        chunks = parse_chunks(response_for(value), value.places, value.sources)
        self.assertEqual(len(select_active(394, chunks)), 20)
        self.assertEqual(select_active(395, chunks), [])
        self.assertEqual(len(chunks), 35)
        self.assertTrue(all('주말에는 혼잡' in item.chunk_text for item in chunks))
        self.assertEqual(len(select_active(394, chunks[:2] + chunks[:2])), 2)

    def test_agent_cannot_change_spans_introduce_places_or_fabricate_quotes(self) -> None:
        value = bundle()
        for mutation in ('offset', 'unknown_place', 'duplicate'):
            with self.subTest(mutation=mutation):
                raw = response_for(value)
                document = json.loads(raw['output'][0]['content'][0]['text'])
                if mutation == 'offset':
                    document['chunks'][0]['end'] += 1
                if mutation == 'unknown_place':
                    document['chunks'][0]['place_refs'][0]['place_id'] = 999
                if mutation == 'duplicate':
                    document['chunks'] *= 2
                raw['output'][0]['content'][0]['text'] = json.dumps(document)
                with self.assertRaises(ValueError):
                    parse_chunks(raw, value.places, value.sources)
        chunk = parse_chunks(response_for(value), value.places, value.sources)[0].to_dict()
        chunk['chunk_text'] = '조작된 리뷰'
        with self.assertRaises(ValueError):
            SearchChunk.from_mapping(value.sources[0], chunk)

    def test_registry_rejects_unknown_source_and_paths_stay_under_place(self) -> None:
        invalid = source(); invalid['source_type'] = 'agent_summary'
        with self.assertRaises(ValueError):
            normalize_source(invalid)
        directory = archive_directory(ExistingPlace(7, '../../위험/장소'))
        self.assertNotIn('/', directory)
        self.assertTrue(directory.startswith('7_'))
        self.assertEqual((ROOT / 'app/contextual/schema.sql').read_bytes(),
                         (ROOT.parent / 'Docker/search-init/03-contextual-chunks.sql').read_bytes())

    def test_existing_collection_bridge_preserves_all_excerpts_for_same_url(self) -> None:
        quote = '평일에 공원 벤치에서 다리를 보았다.'
        url = 'https://example.org/visit'
        document = {'place_id': 394, 'entity_match': 'matched', 'claims': [{
            'aspect': '조망', 'statement': '평일 공원 벤치에서 다리를 본 후기', 'polarity': 'positive',
            'conditions': ['평일'], 'evidence': [{'url': url, 'quote': quote}]}], 'conflicts': [], 'unknowns': []}
        raw = {'status': 'completed', 'output': [
            {'type': 'search_results', 'results': [{'url': url, 'title': '후기', 'snippet': quote}]},
            {'type': 'fetch_url_results', 'contents': [{'url': url, 'title': '후기', 'snippet': quote + ' 주말에는 혼잡했다.'}]},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(document)}]}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text(json.dumps({'status': 'COLLECTED', 'place': PLACE.to_dict(),
                'source_fingerprint': PLACE.source_fingerprint, 'document': normalize_response(PLACE, raw)}))
            path.with_name('raw_response.json').write_text(json.dumps(raw))
            value = SourceBundle.from_enrichment_record(path)
            self.assertEqual(len(value.sources), 2)
            web = next(item for item in value.sources if item.source_type == 'web_excerpt')
            self.assertIn('주말에는 혼잡', web.text)
            self.assertEqual(len(web.metadata['provider_excerpts']), 2)

    async def test_dry_run_cache_archive_revalidation_and_no_key_leak(self) -> None:
        value = bundle()
        calls = []
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            self.assertEqual(json.loads(request.content)['tools'], [])
            return httpx.Response(200, json=response_for(value))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                dry = await collect_bundle(value, SETTINGS, root, None)
                self.assertEqual(json.loads(dry.read_text())['status'], 'PLANNED')
                self.assertNotIn('test-only', dry.with_name('request.json').read_text())
                self.assertFalse(calls)
                first = await collect_bundle(value, SETTINGS, root, http)
                self.assertEqual(first, await collect_bundle(value, SETTINGS, root, http))
                self.assertEqual(len(calls), 1)
                self.assertIn('394_테스트 공원', str(first))
                self.assertTrue((root / '395_조망 다리/references').is_dir())
                self.assertEqual(len(load_record(first)[1]), 1)
                changed = json.loads(first.read_text()); changed['chunks'][0]['context_text'] = '변조'
                first.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'differs'):
                    load_record(first)

    async def test_rate_limit_and_failed_response_are_archived_not_retried(self) -> None:
        calls = []
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(429)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with tempfile.TemporaryDirectory() as directory:
                path = await collect_bundle(bundle(), SETTINGS, Path(directory), http)
                self.assertEqual(json.loads(path.read_text())['http_status'], 429)
                self.assertEqual(len(calls), 1)

    async def test_prompt_versions_preserve_archives_and_have_separate_caches(self) -> None:
        value = bundle()
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=response_for(value))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archived = await collect_bundle(value, SETTINGS, root, http, prompt_version=PromptVersion.V1)
                original_bytes = archived.read_bytes()
                candidate = await collect_bundle(value, SETTINGS, root, http, prompt_version=PromptVersion.V2)
                self.assertNotEqual(archived, candidate)
                for version, expected in ((PromptVersion.V1, archived), (PromptVersion.V2, candidate)):
                    self.assertEqual(await collect_bundle(value, SETTINGS, root, http, prompt_version=version), expected)
                    self.assertEqual(load_record(expected)[1][0].generation['prompt_version'], version)
                self.assertEqual(len(calls), 2)
                self.assertEqual(archived.read_bytes(), original_bytes)
                altered = json.loads(archived.read_text())
                altered['prompt_version'] = PromptVersion.V2
                archived.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, 'changed'):
                    load_record(archived)

    async def test_unattributed_v2_span_is_preserved_but_not_indexed(self) -> None:
        value = bundle()
        raw = response_for(value)
        document = json.loads(raw['output'][0]['content'][0]['text'])
        document['chunks'][0]['place_refs'] = []
        document['chunks'][0]['entities'] = []
        raw['output'][0]['content'][0]['text'] = json.dumps(document)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=raw))) as http:
            with tempfile.TemporaryDirectory() as directory:
                record = await collect_bundle(value, SETTINGS, Path(directory), http)
                preserved, indexed, _ = load_record(record)
                self.assertEqual(indexed, [])
                self.assertEqual(preserved.to_dict(), value.to_dict())
                self.assertEqual(json.loads(record.with_name('raw_response.json').read_text()), raw)

    def test_v2_rejects_unattributed_entities_and_questions_while_v1_remains_readable(self) -> None:
        value = bundle()
        raw = response_for(value)
        document = json.loads(raw['output'][0]['content'][0]['text'])
        document['chunks'][0]['place_refs'] = []
        raw['output'][0]['content'][0]['text'] = json.dumps(document)
        with self.assertRaisesRegex(ValueError, 'both place_refs and entities'):
            parse_chunks(raw, value.places, value.sources)
        self.assertEqual(parse_chunks(raw, value.places, value.sources, prompt_version=PromptVersion.V1), [])
        raw = response_for(value)
        document = json.loads(raw['output'][0]['content'][0]['text'])
        document['chunks'][0]['hypothetical_questions'] = ['주말 혼잡에 관한 방문 경험이 있는가?']
        raw['output'][0]['content'][0]['text'] = json.dumps(document)
        with self.assertRaisesRegex(ValueError, 'Query expansion'):
            parse_chunks(raw, value.places, value.sources)
        self.assertEqual(len(parse_chunks(raw, value.places, value.sources, prompt_version=PromptVersion.V1)), 1)

    async def test_replay_locks_inputs_and_settings_and_detects_provider_model_changes(self) -> None:
        value = bundle()
        responses = [response_for(value), response_for(value)]
        responses[1]['model'] = 'different-provider-model'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=responses.pop(0)))) as http:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archived = await collect_bundle(value, SETTINGS, root, http, prompt_version=PromptVersion.V1)
                baseline = GenerationBaseline.load(archived)
                settings = baseline.settings('test-only', 60)
                payload = request_payload(value.places, value.sources, settings)
                baseline.verify_request(payload)
                for key, replacement in (('model', 'other-model'), ('input', '{}'), ('response_format', {})):
                    altered = copy.deepcopy(payload)
                    altered[key] = replacement
                    with self.assertRaisesRegex(ValueError, 'instructions only'):
                        baseline.verify_request(altered)
                planned = await collect_bundle(value, settings, root, None)
                preview = json.loads(baseline.write_report(planned).read_text())
                self.assertIsNone(preview['actual_model_match'])
                candidate = await collect_bundle(value, settings, root, http)
                report = json.loads(baseline.write_report(candidate).read_text())
                self.assertTrue(report['input_and_settings_match'])
                self.assertFalse(report['actual_model_match'])
                self.assertFalse(report['semantic_quality_evaluated'])

    async def test_unknown_prompt_is_rejected_before_http(self) -> None:
        def unexpected(request: httpx.Request) -> httpx.Response:
            raise AssertionError('Unsupported versions must not call the provider')

        async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, 'Unsupported contextual prompt'):
                    await collect_bundle(bundle(), SETTINGS, Path(directory), http, prompt_version='unregistered-version')


@unittest.skipUnless(os.environ.get('ENRICHMENT_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL test database')
class ContextualDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        import asyncpg
        self.schema = 'contextual_test_' + uuid.uuid4().hex
        self.admin = await asyncpg.connect(os.environ['ENRICHMENT_TEST_DATABASE_URL'])
        await self.admin.execute('CREATE EXTENSION IF NOT EXISTS vector')
        await self.admin.execute(f'CREATE SCHEMA {self.schema}')
        self.pool = await asyncpg.create_pool(os.environ['ENRICHMENT_TEST_DATABASE_URL'], min_size=1, max_size=3,
                                             server_settings={'search_path': self.schema + ',public'})
        await self.pool.execute((ROOT.parent / 'Docker/search-init/01-search-schema.sql').read_text())
        await ensure_schema(self.pool)
        await ensure_schema(self.pool)
        for place in (PLACE, MENTIONED):
            await self.pool.execute('INSERT INTO place_embeddings(place_id,source_version,latest_seen_version,name,description) VALUES($1,1,1,$2,$3)',
                                    place.place_id, place.name, place.description)
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    async def asyncTearDown(self) -> None:
        await self.pool.close()
        await self.admin.execute(f'DROP SCHEMA {self.schema} CASCADE')
        await self.admin.close()
        self.directory.cleanup()

    async def record(self, count: int = 1, context: str = '방문 조건과 조망에 관한 후기') -> Path:
        value = bundle(count)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(value, context)))) as http:
            return await collect_bundle(value, SETTINGS, self.root, http, refresh=True)

    def runtime(self) -> tuple[object, object, object]:
        def embed(texts: list[str]) -> list[list[float]]:
            return [[1.0] + [0.0] * 1023 for text in texts]
        model = SimpleNamespace(device='test', embed=embed)
        with patch.dict(sys.modules, {'app.embedder': SimpleNamespace(embedder=model), 'app.reranker': SimpleNamespace(reranker=SimpleNamespace())}):
            module = importlib.import_module('app.kafka_runtime')
        runtime = object.__new__(module.KafkaRuntime)
        runtime.database_pool = self.pool
        return module, runtime, model

    async def test_full_apply_index_retrieve_archives_all_and_enforces_twenty(self) -> None:
        record = await self.record(32)
        self.assertEqual(await apply_bundle(self.pool, record), 'REINDEX_QUEUED')
        self.assertEqual(await apply_bundle(self.pool, record), 'ALREADY_APPLIED')
        module, runtime, model = self.runtime()
        jobs = await self.pool.fetch('SELECT * FROM place_index_jobs ORDER BY place_id')
        with patch.object(module, 'embedder', model):
            for job in jobs:
                await runtime._index_place_job(job)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM place_active_chunks WHERE place_id=394'), 20)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM place_active_chunks WHERE place_id=395'), 0)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM retrieval_chunks'), 33)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM retrieval_source_versions'), 33)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM place_index_jobs'), 2)
        vector = '[' + ','.join(['1'] + ['0'] * 1023) + ']'
        candidates = await runtime._retrieve_candidates({'filters': {}}, vector)
        self.assertEqual(len(candidates), 2)
        target = next(item for item in candidates if item['place_id'] == 394)
        result = runtime._to_result_item(target, 1, None)
        self.assertEqual(len(result['evidence_chunks']), 1)
        self.assertIn('source_span', result['evidence_chunks'][0])
        self.assertEqual(await self.pool.fetchval('SELECT description FROM place_embeddings WHERE place_id=394'), PLACE.description)
        import asyncpg
        with self.assertRaises(asyncpg.CheckViolationError):
            await self.pool.execute('INSERT INTO place_active_chunks(place_id,slot,chunk_id,context_version) SELECT place_id,21,chunk_id,context_version FROM place_active_chunks LIMIT 1')
        with self.assertRaises(asyncpg.CheckViolationError):
            await self.pool.execute('INSERT INTO place_active_chunks(place_id,slot,chunk_id,context_version) SELECT 395,1,chunk_id,context_version FROM place_active_chunks WHERE place_id=394 LIMIT 1')

    async def test_context_refresh_keeps_chunk_id_and_source_archive(self) -> None:
        first = await self.record()
        await apply_bundle(self.pool, first)
        second = await self.record(context='문맥을 갱신한 방문 후기')
        await apply_bundle(self.pool, second)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM retrieval_chunks'), 1)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM retrieval_source_versions'), 1)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM retrieval_chunk_contexts'), 2)
        generation, chunks = await desired_chunks(self.pool, PLACE)
        self.assertEqual(generation, 2)
        self.assertEqual(chunks[0].context_text, '문맥을 갱신한 방문 후기')

    async def test_source_change_rejects_old_bundle_and_old_context_is_not_reused(self) -> None:
        record = await self.record()
        await apply_bundle(self.pool, record)
        await self.pool.execute("UPDATE place_embeddings SET description='새 공식 설명' WHERE place_id=394")
        with self.assertRaisesRegex(ValueError, 'changed'):
            await apply_bundle(self.pool, record)
        changed = ExistingPlace(394, PLACE.name, description='새 공식 설명')
        self.assertEqual((await desired_chunks(self.pool, changed))[1], [])

    async def test_new_context_during_inference_cannot_overwrite_active_generation(self) -> None:
        await apply_bundle(self.pool, await self.record())
        newer = await self.record(context='새로운 문맥')
        module, runtime, model = self.runtime()
        calls = 0
        async def infer(function):
            nonlocal calls
            calls += 1
            if calls == 1:
                await apply_bundle(self.pool, newer)
            return function()
        job = await self.pool.fetchrow('SELECT * FROM place_index_jobs WHERE place_id=394 LIMIT 1')
        with patch.object(module, 'embedder', model), patch.object(module.to_thread, 'run_sync', side_effect=infer):
            await runtime._index_place_job(job)
        self.assertEqual(await self.pool.fetchval('SELECT status FROM place_index_jobs WHERE job_id=$1', job['job_id']), 'SUPERSEDED')
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM place_active_chunks'), 0)

    @unittest.skipUnless(os.environ.get('CONTEXTUAL_MODEL_TEST_URL'), 'Requires running unchanged BGE model service')
    async def test_real_bge_models_index_context_and_rerank_original_evidence(self) -> None:
        base = os.environ['CONTEXTUAL_MODEL_TEST_URL'].rstrip('/')
        def request(path: str, payload: dict) -> dict:
            message = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(message, timeout=120) as response:
                return json.load(response)
        class RemoteEmbedder:
            device = 'existing-bge-service'
            def embed(self, texts: list[str]) -> list[list[float]]:
                return request('/embed', {'texts': texts})['embeddings']
        await apply_bundle(self.pool, await self.record())
        module, runtime, unused_model = self.runtime()
        job = await self.pool.fetchrow('SELECT * FROM place_index_jobs WHERE place_id=394 LIMIT 1')
        model = RemoteEmbedder()
        with patch.object(module, 'embedder', model):
            await runtime._index_place_job(job)
        query = '평일에 공원 벤치에서 다리를 볼 수 있을까?'
        vector = model.embed([query])[0]
        candidates = await runtime._retrieve_candidates({'filters': {}}, '[' + ','.join(map(str, vector)) + ']')
        self.assertEqual(candidates[0]['place_id'], 394)
        evidence = runtime._to_result_item(candidates[0], 1, None)['evidence_chunks'][0]
        self.assertIn('주말에는 혼잡했다', evidence['chunk_text'])
        scores = request('/rerank', {'query': query, 'texts': [candidates[0]['description'], '컴퓨터 프로그래밍 언어의 문법']})['scores']
        self.assertGreater(scores[0], scores[1])


if __name__ == '__main__':
    unittest.main()
