"""Mocked Agent responses and isolated PostgreSQL tests; no paid requests or model inference."""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.enrichment.agent import AGENT_ENDPOINT, AgentClient, AgentSettings, request_payload
from app.enrichment.artifacts import collect_place
from app.enrichment.contracts import CollectionStatus, EvidenceStatus, ExistingPlace
from app.enrichment.evidence import normalize_response, search_description, searchable_claims
from app.enrichment.repository import apply_record, ensure_schema, latest_snapshot

PLACE = ExistingPlace(place_id=394, name='테스트 도로공원', description='관광지. 근린공원', region='서울', city='강남', latitude=37.5, longitude=127.0)
SOURCE = 'https://example.org/reviews/road-park'
QUOTE = '해질 무렵 다리 조명을 보기 좋았어요.'


def agent_response(*, quote: str = QUOTE, url: str = SOURCE, entity_match: str = 'matched', conflicts: list | None = None) -> dict:
    result = {'place_id': PLACE.place_id, 'entity_match': entity_match, 'claims': [{
        'aspect': '야경', 'statement': '다리의 야간 조명을 감상했다는 후기', 'polarity': 'positive',
        'conditions': ['해질 무렵'], 'evidence': [{'url': url, 'quote': quote}],
    }], 'conflicts': conflicts or [], 'unknowns': ['현재 화장실 운영 여부']}
    return {'id': 'mock-response', 'model': 'mock-model', 'status': 'completed', 'usage': {'input_tokens': 100}, 'output': [
        {'type': 'search_results', 'results': [{'url': SOURCE, 'title': '테스트 도로공원 후기', 'snippet': QUOTE}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': json.dumps(result, ensure_ascii=False)}]},
    ]}


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def test_explicit_model_selection_and_no_key_in_repr(self) -> None:
        with self.assertRaises(ValueError):
            AgentSettings()
        with self.assertRaises(ValueError):
            AgentSettings(preset='one', model='two')
        self.assertNotIn('unit-secret', repr(AgentSettings(preset='test', api_key='unit-secret')))

    def test_request_uses_responses_schema_and_exact_existing_identity(self) -> None:
        payload = request_payload(PLACE, AgentSettings(preset='test'))
        self.assertEqual(json.loads(payload['input'])['place_id'], PLACE.place_id)
        self.assertEqual(payload['response_format']['type'], 'json_schema')
        self.assertEqual([item['type'] for item in payload['tools']], ['web_search', 'fetch_url'])
        self.assertFalse(payload['background'])

    def test_existing_source_fingerprint_stays_stable_and_changes_with_description(self) -> None:
        self.assertEqual(PLACE.source_fingerprint, ExistingPlace.from_mapping(PLACE.to_dict()).source_fingerprint)
        changed = {**PLACE.to_dict(), 'description': '바뀐 공식 소개'}
        self.assertNotEqual(PLACE.source_fingerprint, ExistingPlace.from_mapping(changed).source_fingerprint)

    def test_exact_quote_requires_provider_tool_output_not_generated_json(self) -> None:
        valid = normalize_response(PLACE, agent_response())
        self.assertTrue(valid['claims'][0]['searchable'])
        self.assertEqual(valid['claims'][0]['evidence'][0]['status'], EvidenceStatus.EXCERPT_MATCHED)
        fabricated = normalize_response(PLACE, agent_response(quote='실제로 반환되지 않은 인용'))
        self.assertFalse(fabricated['claims'][0]['searchable'])
        unknown_url = normalize_response(PLACE, agent_response(url='https://example.org/invented'))
        self.assertFalse(unknown_url['claims'][0]['searchable'])
        only_message = agent_response(); only_message['output'] = only_message['output'][1:]
        self.assertFalse(normalize_response(PLACE, only_message)['claims'][0]['searchable'])

    def test_wrong_place_and_incomplete_response_cannot_be_indexed(self) -> None:
        response = agent_response(); response['status'] = 'in_progress'
        with self.assertRaises(ValueError):
            normalize_response(PLACE, response)
        wrong = ExistingPlace(place_id=999, name=PLACE.name)
        with self.assertRaises(ValueError):
            normalize_response(wrong, agent_response())
        self.assertFalse(searchable_claims(normalize_response(PLACE, agent_response(entity_match='mismatch'))))

    def test_conflicts_are_retained_and_not_indexed_as_facts(self) -> None:
        normalized = normalize_response(PLACE, agent_response(conflicts=[{'aspect': '야경', 'reason': '출처 간 평가가 다름'}]))
        self.assertTrue(normalized['conflicts'])
        self.assertFalse(searchable_claims(normalized))
        self.assertEqual(search_description(PLACE, normalized), PLACE.description)

    def test_fetch_url_excerpts_and_conditions_are_preserved(self) -> None:
        raw = agent_response()
        raw['output'][0] = {'type': 'fetch_url_results', 'contents': [{'url': SOURCE, 'title': '공원', 'snippet': '주말 밤에는 조명이 어두웠어요.'}]}
        document = json.loads(raw['output'][1]['content'][0]['text'])
        document['claims'][0].update(statement='어두웠다는 후기', polarity='negative', conditions=['주말 밤'])
        document['claims'][0]['evidence'][0]['quote'] = '주말 밤에는 조명이 어두웠어요.'
        raw['output'][1]['content'][0]['text'] = json.dumps(document)
        normalized = normalize_response(PLACE, raw)
        text = search_description(PLACE, normalized)
        self.assertIn('주말 밤', text)
        self.assertIn('어두웠다는 후기', text)
        self.assertIn(SOURCE, text)
        self.assertTrue(normalized['unknowns'])

    async def test_dry_run_makes_no_requests_and_archives_no_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = await collect_place(PLACE, AgentSettings(preset='test', api_key='unit-secret'), Path(directory), None)
            record = json.loads(path.read_text())
            self.assertEqual(record['status'], CollectionStatus.PLANNED)
            self.assertNotIn('unit-secret', path.with_name('request.json').read_text())
            self.assertFalse(path.with_name('raw_response.json').exists())

    async def test_http_adapter_cache_refresh_and_changed_source(self) -> None:
        requests = []
        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            self.assertEqual(str(request.url), AGENT_ENDPOINT)
            self.assertEqual(json.loads(request.content)['preset'], 'test')
            return httpx.Response(200, json=agent_response())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            settings = AgentSettings(preset='test', api_key='unit-key')
            client = AgentClient(http, settings)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                first = await collect_place(PLACE, settings, root, client)
                second = await collect_place(PLACE, settings, root, client)
                self.assertEqual(first, second)
                self.assertEqual(len(requests), 1)
                third = await collect_place(PLACE, settings, root, client, refresh=True)
                self.assertNotEqual(first, third)
                self.assertTrue(first.exists())
                changed = ExistingPlace.from_mapping({**PLACE.to_dict(), 'description': '변경됨'})
                fourth = await collect_place(changed, settings, root, client)
                self.assertNotEqual(third.parent.parent, fourth.parent.parent)
                self.assertEqual(len(requests), 3)

    async def test_invalid_response_preserves_raw_and_does_not_become_success(self) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'status': 'completed', 'output': []}))) as http:
            with tempfile.TemporaryDirectory() as directory:
                path = await collect_place(PLACE, AgentSettings(preset='test', api_key='test'), Path(directory), AgentClient(http, AgentSettings(preset='test', api_key='test')))
                self.assertEqual(json.loads(path.read_text())['status'], CollectionStatus.FAILED)
                self.assertTrue(path.with_name('raw_response.json').exists())

    async def test_http_failure_is_not_automatically_retried(self) -> None:
        attempts = []
        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            return httpx.Response(429, json={'error': 'rate limited'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            settings = AgentSettings(preset='test', api_key='unit-key')
            with tempfile.TemporaryDirectory() as directory:
                path = await collect_place(PLACE, settings, Path(directory), AgentClient(http, settings))
                self.assertEqual(json.loads(path.read_text())['status'], CollectionStatus.FAILED)
                self.assertEqual(json.loads(path.read_text())['http_status'], 429)
                self.assertEqual(len(attempts), 1)

    def test_docker_init_schema_matches_runtime_schema(self) -> None:
        self.assertEqual((ROOT / 'app/enrichment/schema.sql').read_bytes(), (ROOT.parent / 'Docker/search-init/02-place-enrichment.sql').read_bytes())


@unittest.skipUnless(os.environ.get('ENRICHMENT_TEST_DATABASE_URL'), 'Requires an explicitly isolated PostgreSQL test database')
class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        import asyncpg
        self.schema = 'enrichment_test_' + uuid.uuid4().hex
        self.admin = await asyncpg.connect(os.environ['ENRICHMENT_TEST_DATABASE_URL'])
        await self.admin.execute('CREATE EXTENSION IF NOT EXISTS vector')
        await self.admin.execute(f'CREATE SCHEMA {self.schema}')
        self.pool = await asyncpg.create_pool(os.environ['ENRICHMENT_TEST_DATABASE_URL'], min_size=1, max_size=2, server_settings={'search_path': self.schema + ',public'})
        await self.pool.execute((ROOT.parent / 'Docker/search-init/01-search-schema.sql').read_text())
        await ensure_schema(self.pool)
        await ensure_schema(self.pool)
        await self.pool.execute("INSERT INTO place_embeddings (place_id,source_version,latest_seen_version,name,description,region,city,latitude,longitude) VALUES ($1,1,1,$2,$3,$4,$5,$6,$7)", PLACE.place_id, PLACE.name, PLACE.description, PLACE.region, PLACE.city, PLACE.latitude, PLACE.longitude)
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=agent_response()))) as http:
            settings = AgentSettings(preset='test', api_key='unit-key')
            self.record = await collect_place(PLACE, settings, self.root, AgentClient(http, settings))

    async def asyncTearDown(self) -> None:
        await self.pool.close()
        await self.admin.execute(f'DROP SCHEMA {self.schema} CASCADE')
        await self.admin.close()
        self.directory.cleanup()

    async def test_application_is_idempotent_and_preserves_basic_facts(self) -> None:
        self.assertEqual(await apply_record(self.pool, self.record), 'REINDEX_QUEUED')
        self.assertEqual(await apply_record(self.pool, self.record), 'ALREADY_APPLIED')
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM place_index_jobs'), 1)
        row = dict(await self.pool.fetchrow('SELECT * FROM place_embeddings WHERE place_id=$1', PLACE.place_id))
        self.assertEqual(ExistingPlace.from_mapping(row), PLACE)
        self.assertIsNone(row['search_description'])  # Index worker, not the collector, owns the vector/document update.
        self.assertIsNotNone(await latest_snapshot(self.pool, PLACE))

    async def test_changed_deleted_and_pending_sources_reject_old_enrichment(self) -> None:
        await self.pool.execute("UPDATE place_embeddings SET description='바뀐 소개' WHERE place_id=$1", PLACE.place_id)
        with self.assertRaisesRegex(ValueError, 'changed'):
            await apply_record(self.pool, self.record)
        await self.pool.execute("UPDATE place_embeddings SET description=$2, document_status='DELETED' WHERE place_id=$1", PLACE.place_id, PLACE.description)
        with self.assertRaises(ValueError):
            await apply_record(self.pool, self.record)
        await self.pool.execute("UPDATE place_embeddings SET document_status='READY', latest_seen_version=2 WHERE place_id=$1", PLACE.place_id)
        with self.assertRaises(ValueError):
            await apply_record(self.pool, self.record)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM place_enrichment_snapshots'), 0)

    async def test_tampered_record_is_rejected_before_database_writes(self) -> None:
        record = json.loads(self.record.read_text())
        record['document']['claims'][0]['statement'] = '임의로 고친 주장'
        self.record.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'differs'):
            await apply_record(self.pool, self.record)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM place_index_jobs'), 0)

    async def test_index_worker_uses_enrichment_and_preserves_reranker_path(self) -> None:
        await apply_record(self.pool, self.record)
        embedded = []
        def embed(texts: list[str]) -> list[list[float]]:
            embedded.extend(texts)
            return [([1.0, 0.0] if QUOTE in text else [0.0, 1.0]) + [0.0] * 1022 for text in texts]
        fake_embedder = SimpleNamespace(device='unit-test', embed=embed)
        with patch.dict(sys.modules, {'app.embedder': SimpleNamespace(embedder=fake_embedder), 'app.reranker': SimpleNamespace(reranker=SimpleNamespace())}):
            runtime_module = importlib.import_module('app.kafka_runtime')
        runtime = object.__new__(runtime_module.KafkaRuntime)
        runtime.database_pool = self.pool
        job = await self.pool.fetchrow('SELECT * FROM place_index_jobs LIMIT 1')
        with patch.object(runtime_module, 'embedder', fake_embedder):
            await runtime._index_place_job(job)
        row = await self.pool.fetchrow('SELECT * FROM place_embeddings WHERE place_id=$1', PLACE.place_id)
        self.assertEqual(row['description'], PLACE.description)
        self.assertIn(QUOTE, row['search_description'])
        self.assertTrue(any(QUOTE in text for text in embedded))
        self.assertIsNotNone(row['enrichment_snapshot_id'])
        self.assertEqual(await self.pool.fetchval('SELECT status FROM place_index_jobs LIMIT 1'), 'SUCCEEDED')
        candidates = await runtime._retrieve_candidates({'filters': {}}, '[' + ','.join(['1'] + ['0'] * 1023) + ']')
        self.assertIn(QUOTE, candidates[0]['description'])
        result = runtime._to_result_item(candidates[0], 1, None)
        self.assertEqual(result['enrichment_snapshot_id'], str(row['enrichment_snapshot_id']))

    async def test_newer_enrichment_during_embedding_supersedes_the_old_job(self) -> None:
        await apply_record(self.pool, self.record)
        old_job = await self.pool.fetchrow('SELECT * FROM place_index_jobs LIMIT 1')
        refreshed = self.root / 'newer'
        refreshed.mkdir()
        newer = json.loads(self.record.read_text())
        newer['snapshot_id'] = str(uuid.uuid4())
        newer['collected_at'] = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
        (refreshed / 'record.json').write_text(json.dumps(newer))
        (refreshed / 'raw_response.json').write_text(self.record.with_name('raw_response.json').read_text())
        fake_embedder = SimpleNamespace(device='unit-test')
        with patch.dict(sys.modules, {'app.embedder': SimpleNamespace(embedder=fake_embedder), 'app.reranker': SimpleNamespace(reranker=SimpleNamespace())}):
            runtime_module = importlib.import_module('app.kafka_runtime')
        runtime = object.__new__(runtime_module.KafkaRuntime)
        runtime.database_pool = self.pool
        async def compute_after_newer_snapshot(*args: object) -> list[list[float]]:
            await apply_record(self.pool, refreshed / 'record.json')
            return [[1.0] + [0.0] * 1023]
        with patch.object(runtime_module, 'embedder', fake_embedder), patch.object(runtime_module.to_thread, 'run_sync', new=AsyncMock(side_effect=compute_after_newer_snapshot)):
            await runtime._index_place_job(old_job)
        self.assertEqual(await self.pool.fetchval('SELECT status FROM place_index_jobs WHERE job_id=$1', old_job['job_id']), 'SUPERSEDED')
        self.assertIsNone(await self.pool.fetchval('SELECT enrichment_snapshot_id FROM place_embeddings WHERE place_id=$1', PLACE.place_id))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM place_index_jobs WHERE status='PENDING'"), 1)

    async def test_plain_place_index_keeps_original_and_adds_contextual_tourapi_chunk(self) -> None:
        event_id = uuid.uuid4()
        job_id = uuid.uuid4()
        payload = {'event_id': str(event_id), 'event_type': 'PLACE_UPSERTED', 'place_id': PLACE.place_id, 'source_version': 1, 'source': PLACE.to_dict()}
        await self.pool.execute('INSERT INTO place_index_jobs(job_id,event_id,place_id,source_version,payload) VALUES($1,$2,$3,1,$4::jsonb)', job_id, event_id, PLACE.place_id, json.dumps(payload))
        inputs = []
        def embed(texts: list[str]) -> list[list[float]]:
            inputs.extend(texts)
            return [[1.0] + [0.0] * 1023 for text in texts]
        fake_embedder = SimpleNamespace(device='unit-test', embed=embed)
        with patch.dict(sys.modules, {'app.embedder': SimpleNamespace(embedder=fake_embedder), 'app.reranker': SimpleNamespace(reranker=SimpleNamespace())}):
            runtime_module = importlib.import_module('app.kafka_runtime')
        runtime = object.__new__(runtime_module.KafkaRuntime)
        runtime.database_pool = self.pool
        job = await self.pool.fetchrow('SELECT * FROM place_index_jobs WHERE job_id=$1', job_id)
        with patch.object(runtime_module, 'embedder', fake_embedder):
            await runtime._index_place_job(job)
        self.assertEqual(inputs, [f'{PLACE.name}. TourAPI 장소 설명의 일부이다.\n\n{PLACE.description}'])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM place_active_chunks'), 1)
        self.assertIsNone(await self.pool.fetchval('SELECT search_description FROM place_embeddings WHERE place_id=$1', PLACE.place_id))


if __name__ == '__main__':
    unittest.main()
