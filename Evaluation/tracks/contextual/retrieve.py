"""보존 응답을 임시 스키마에 색인하고 실제 검색·리랭킹 코드를 실행한다.

임베딩 컨테이너에서 실행한다. 공개 스키마와 Kafka 작업에는 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any
import uuid

import asyncpg
import httpx


class LocalModels:
    device = 'existing-http-server'
    model_name = 'existing-http-server'
    batch_size = 8
    execution_mode = 'existing-http-server'

    def __init__(self) -> None:
        self.embeddings: dict[str, list[float]] = {}
        self.calls = {'embed': 0, 'rerank': 0}
        self.client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=180, trust_env=False)

    def embed(self, texts: list[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(text for text in texts if text not in self.embeddings))
        if missing:
            response = self.client.post('/embed', json={'texts': missing})
            response.raise_for_status()
            self.calls['embed'] += 1
            vectors = response.json()['embeddings']
            if len(vectors) != len(missing):
                raise ValueError('임베딩 개수가 입력과 다릅니다')
            for text, vector in zip(missing, vectors, strict=True):
                if len(vector) != 1024 or not all(math.isfinite(value) for value in vector):
                    raise ValueError('유효하지 않은 임베딩입니다')
                self.embeddings[text] = vector
        return [self.embeddings[text] for text in texts]

    def rerank(self, query: str, texts: list[str], execution_wait_ms: float = 0) -> list[float]:
        response = self.client.post('/rerank', json={'query': query, 'texts': texts})
        response.raise_for_status()
        self.calls['rerank'] += 1
        scores = response.json()['scores']
        if len(scores) != len(texts) or not all(math.isfinite(score) for score in scores):
            raise ValueError('유효하지 않은 리랭킹 점수입니다')
        return scores

    def getDimension(self) -> int:
        return 1024

    def batch_count(self, count: int) -> int:
        return math.ceil(count / self.batch_size)


def write_new(path: Path, document: Any) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)


async def public_fingerprint(connection: Any) -> dict[str, Any]:
    row = await connection.fetchrow("""SELECT count(*) AS places,
        md5(string_agg(to_jsonb(p)::text, '' ORDER BY place_id)) AS content_md5
        FROM public.place_embeddings p""")
    return dict(row)


async def main(args: argparse.Namespace) -> None:
    inputs = json.loads(args.inputs.read_text(encoding='utf-8'))
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    if args.output.exists():
        raise ValueError('기존 결과를 덮어쓰지 않습니다')
    args.output.mkdir(parents=True)
    models = LocalModels()
    # 기존 서버의 모델을 재사용하여 같은 GPU에 두 번째 모델을 적재하지 않는다.
    for module_name, attribute in (('app.embedder', 'embedder'), ('app.reranker', 'reranker')):
        proxy = ModuleType(module_name)
        setattr(proxy, attribute, models)
        sys.modules[module_name] = proxy
    from app.contextual.contracts import SearchChunk, SourceDocument
    from app.contextual.pipeline import select_active, tourapi_chunks
    from app.contextual.repository import activate_chunks
    from app.enrichment.contracts import ExistingPlace
    from app.kafka_runtime import KafkaRuntime, RankingMode, RETRIEVE_TOP_K

    class CapturingRuntime(KafkaRuntime):
        def __init__(self, pool: Any) -> None:
            self.database_pool = pool
            self.captured: dict[str, Any] = {}
            self.candidates: list[dict[str, Any]] = []

        async def _retrieve_candidates(self, payload: dict[str, Any], vector: str) -> list[dict[str, Any]]:
            self.candidates = await super()._retrieve_candidates(payload, vector)
            return self.candidates

        async def _save_recommendation_result(self, request: Any, result: dict[str, Any]) -> None:
            self.captured = result

    schemas = {version: f'contextual_eval_{uuid.uuid4().hex}_{version}' for version in ('v1', 'v2')}
    created: list[str] = []
    pools: dict[str, Any] = {}
    connection = await asyncpg.connect(os.environ['DATABASE_URL'])
    completed = []
    try:
        before = await public_fingerprint(connection)
        async with connection.transaction(isolation='repeatable_read'):
            for schema in schemas.values():
                await connection.execute(f'CREATE SCHEMA "{schema}"')
                created.append(schema)
                await connection.execute(f'CREATE TABLE "{schema}".place_embeddings (LIKE public.place_embeddings INCLUDING ALL)')
                await connection.execute(f'INSERT INTO "{schema}".place_embeddings SELECT * FROM public.place_embeddings')
                await connection.execute(f'SET LOCAL search_path TO "{schema}", public')
                local_namespace = await connection.fetchval("SELECT relnamespace::regnamespace::text FROM pg_class WHERE oid='place_embeddings'::regclass")
                if local_namespace != schema:
                    raise ValueError('평가 전용 테이블 격리에 실패했습니다')
                await connection.execute((args.code / 'app/enrichment/schema.sql').read_text(encoding='utf-8'))
                await connection.execute((args.code / 'app/contextual/schema.sql').read_text(encoding='utf-8'))
        snapshot = {version: await connection.fetchval(f'SELECT md5(string_agg(to_jsonb(p)::text, \'\' ORDER BY place_id)) FROM "{schema}".place_embeddings p')
                    for version, schema in schemas.items()}
        if len(set(snapshot.values())) != 1:
            raise ValueError('대조군 배경 장소 스냅샷이 다릅니다')
        for version, schema in schemas.items():
            pools[version] = await asyncpg.create_pool(
                os.environ['DATABASE_URL'], min_size=1, max_size=1,
                server_settings={'search_path': f'"{schema}", public'}, command_timeout=30)
        health = models.client.get('/health').json()
        await asyncio.to_thread(models.embed, [query['query'] for query in cases['queries']])
        target_id = cases['target_place_id']
        for pair_index, pair in enumerate(inputs['pairs']):
            installed = {}
            for version in schemas:
                record = pair[version]
                place = ExistingPlace.from_mapping(record['place'])
                actual = await pools[version].fetchrow('SELECT * FROM place_embeddings WHERE place_id=$1', target_id)
                if ExistingPlace.from_mapping(dict(actual)).source_fingerprint != place.source_fingerprint:
                    raise ValueError('저장된 장소와 평가 DB의 장소가 다릅니다')
                sources = {source['source_id']: SourceDocument.from_mapping(source) for source in record['sources']}
                chunks = [SearchChunk.from_mapping(sources[chunk['source_id']], chunk) for chunk in record['chunks']]
                active = select_active(target_id, chunks + tourapi_chunks(place))
                vectors = await asyncio.to_thread(models.embed, [chunk.embedding_text for chunk in active])
                async with pools[version].acquire() as private:
                    async with private.transaction():
                        await activate_chunks(private, target_id, active, vectors)
                installed[version] = [chunk.to_dict() for chunk in active]
            write_new(args.output / f"{pair['id']}-active.json", installed)
            queries = [query for query in cases['queries'] if query['pair_id'] == pair['id']]
            for query_index, query in enumerate(queries):
                versions = ('v1', 'v2') if (pair_index + query_index) % 2 == 0 else ('v2', 'v1')
                for version in versions:
                    runtime = CapturingRuntime(pools[version])
                    now = datetime.now(UTC)
                    payload = {'query': query['query'], 'ranking_mode': RankingMode.RERANKED.value,
                               'limit': 20, 'requested_at': now.isoformat(), 'filters': {}}
                    await runtime._complete_recommendation({'request_id': str(uuid.uuid4()), 'context_version': 1,
                                                           'created_at': now, 'payload': json.dumps(payload)})
                    result = {'query_id': query['id'], 'version': version, 'pair_id': pair['id'],
                              'query': query['query'], 'kind': query['kind'], 'result': runtime.captured,
                              'semantic_candidates': [{'place_id': candidate['place_id'],
                                  'semantic_score': candidate['semantic_score'],
                                  'evidence': json.loads(candidate['evidence']) if candidate.get('evidence') else None}
                                  for candidate in runtime.candidates]}
                    write_new(args.output / f"{query['id']}-{version}.json", result)
                    completed.append({'query_id': query['id'], 'version': version})
                    print(json.dumps({'completed': len(completed), 'total': len(cases['queries']) * 2,
                                      'query_id': query['id'], 'version': version}), flush=True)
        vectors = [{'text': text, 'embedding': vector} for text, vector in models.embeddings.items()]
        write_new(args.output / 'vectors.json', vectors)
        write_new(args.output / 'run.json', {
            'status': 'COMPLETED', 'created_at': datetime.now(UTC).isoformat(),
            'scope': 'actual core recommendation worker; no Spring/Kafka delivery or final answer generation',
            'target_place_id': target_id, 'public_before': before, 'snapshot_md5': snapshot,
            'queries': len(cases['queries']), 'completed': completed, 'retrieve_top_k': RETRIEVE_TOP_K,
            'health': health, 'http_calls': models.calls, 'perplexity_calls': 0,
            'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(),
            'inputs_sha256': hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
            'runtime_sha256': hashlib.sha256((args.code / 'app/kafka_runtime.py').read_bytes()).hexdigest(),
            'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'model_configuration': {key: os.environ.get(key) for key in ('EMBEDDING_MODEL', 'EMBEDDING_REVISION',
                'RERANK_BATCH_SIZE', 'RERANK_EXECUTION_STRATEGY')},
            'schemas': schemas, 'installation': 'each input pair separately; subject chunks plus TourAPI fallback; latest activate_chunks/select_active',
        })
    except Exception as exception:
        write_new(args.output / 'failure.json', {'error_type': type(exception).__name__, 'completed': completed})
        raise
    finally:
        for pool in pools.values():
            await pool.close()
        for schema in created:
            # 이 실행에서 직접 만든 이름만 제거한다. 공개 스키마는 절대 대상으로 삼지 않는다.
            if schema not in schemas.values() or not schema.startswith('contextual_eval_'):
                raise ValueError('평가 스키마 정리 범위가 잘못되었습니다')
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        after = await public_fingerprint(connection)
        remaining = await connection.fetchval('SELECT count(*) FROM pg_namespace WHERE nspname=ANY($1::text[])', list(schemas.values()))
        write_new(args.output / 'cleanup.json', {'schemas_remaining': remaining, 'public_after': after,
                                                'public_unchanged': before == after})
        await connection.close()
        models.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    sys.path.insert(0, str(arguments.code))
    asyncio.run(main(arguments))
