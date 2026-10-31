"""저장 v2·고정 후보로 근거 1/2/3개를 비교한다. 임베딩 컨테이너 전용이다."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import ModuleType
from typing import Any
import uuid

import asyncpg
from transformers import AutoTokenizer
from retrieve import LocalModels, public_fingerprint, write_new
from score import evidence_id


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordingModels(LocalModels):
    def __init__(self, vectors: Path) -> None:
        super().__init__()
        self.embeddings = {item['text']: item['embedding'] for item in json.loads(vectors.read_text())}
        self.tokenizer = AutoTokenizer.from_pretrained('BAAI/bge-reranker-v2-m3', local_files_only=True)
        self.last_call: dict[str, Any] = {}

    def input_token_lengths(self, query: str, texts: list[str]) -> list[int]:
        return self.tokenizer([query] * len(texts), texts, padding=False, truncation=True,
            max_length=self.tokenizer.model_max_length, return_length=True)['length']

    def rerank(self, query: str, texts: list[str], execution_wait_ms: float = 0) -> list[float]:
        started = time.perf_counter()
        scores = super().rerank(query, texts, execution_wait_ms)
        self.last_call = {'texts': texts, 'scores': scores, 'http_elapsed_ms': (time.perf_counter() - started) * 1000,
                          'worker_dispatch_wait_ms': execution_wait_ms}
        return scores


class GpuSampler:
    def __init__(self) -> None:
        self.samples: list[tuple[float, int, int]] = []
        self.process: Any = None
        self.thread: Any = None

    def start(self) -> None:
        try:
            self.process = subprocess.Popen(['nvidia-smi', '--query-gpu=memory.used,memory.total',
                '--format=csv,noheader,nounits', '--loop-ms=100'], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True)
        except OSError:
            return
        def collect() -> None:
            for line in self.process.stdout:
                try:
                    used, total = map(int, line.strip().split(','))
                    self.samples.append((time.perf_counter(), used, total))
                except ValueError:
                    continue
        self.thread = threading.Thread(target=collect, daemon=True)
        self.thread.start()

    def window(self, start: float, end: float) -> dict[str, Any]:
        selected = [sample for sample in self.samples if start <= sample[0] <= end]
        return {'samples': len(selected), 'device_peak_used_mib': max((sample[1] for sample in selected), default=None)}

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.thread.join(timeout=2)


def distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {'samples': len(ordered), 'p50': ordered[(len(ordered) - 1) // 2],
            'p95': ordered[max(0, __import__('math').ceil(len(ordered) * 0.95) - 1)],
            'min': ordered[0], 'max': ordered[-1]}


def summarize(observed: list[dict[str, Any]]) -> dict[str, Any]:
    variants = {}
    for count in (1, 2, 3):
        rows = [row for row in observed if row['evidence_count'] == count]
        supported = [row for row in rows if row['kind'] == 'supported']
        variants[str(count)] = {
            'supported_samples': len(supported),
            'target_top_1': sum(row['target_rank'] == 1 for row in supported),
            'target_top_5': sum(row['target_rank'] is not None and row['target_rank'] <= 5 for row in supported),
            'gold_delivered': sum(row['gold_delivered'] for row in supported),
            'gold_winner_top_5': sum(row['gold_winner_top_5'] for row in supported),
            'gold_any_returned_top_5': sum(row['gold_any_returned_top_5'] for row in supported),
            'known_wrong_place_winner': sum(row['known_wrong_place_winner'] for row in rows),
            'known_wrong_place_returned': sum(row['known_wrong_place_returned'] for row in rows),
            'pair_count': distribution([row['pair_count'] for row in rows]),
            'token_count': distribution([row['input_tokens'] for row in rows]),
            'core_elapsed_ms': distribution([row['core_elapsed_ms'] for row in rows]),
            'rerank_http_ms': distribution([row['rerank_http_ms'] for row in rows]),
            'database_ms': distribution([row['database_ms'] for row in rows]),
            'worker_dispatch_wait_ms': distribution([row['worker_dispatch_wait_ms'] for row in rows]),
        }
    return variants


async def main(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError('실행 폴더를 덮어쓰지 않습니다')
    args.output.mkdir(parents=True)
    inputs = json.loads(args.inputs.read_text(encoding='utf-8'))
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    prepared = json.loads(args.prepared.read_text(encoding='utf-8'))
    models = RecordingModels(args.vectors)
    for module_name, attribute in (('app.embedder', 'embedder'), ('app.reranker', 'reranker')):
        proxy = ModuleType(module_name)
        setattr(proxy, attribute, models)
        sys.modules[module_name] = proxy
    from app.contextual.contracts import SearchChunk, SourceDocument
    from app.contextual.pipeline import select_active, tourapi_chunks
    from app.contextual.ranking import EvidenceCount, build_pairs, MAX_RERANK_PAIRS, MAX_RERANK_TOKENS
    from app.contextual.repository import activate_chunks
    from app.enrichment.contracts import ExistingPlace
    from app.kafka_runtime import KafkaRuntime

    class RecordingRuntime(KafkaRuntime):
        def __init__(self, pool: Any, count: int) -> None:
            self.database_pool = pool
            self.evidence_count = EvidenceCount(count)
            self.candidates: list[dict[str, Any]] = []
            self.expanded: list[dict[str, Any]] = []
            self.result: dict[str, Any] = {}
            self.database_ms = 0.0

        async def _retrieve_candidates(self, payload: dict[str, Any], vector: str) -> list[dict[str, Any]]:
            started = time.perf_counter()
            self.candidates = await super()._retrieve_candidates(payload, vector)
            self.database_ms += (time.perf_counter() - started) * 1000
            return self.candidates

        async def _retrieve_evidence(self, candidates: Any, vector: str, count: Any) -> list[dict[str, Any]]:
            started = time.perf_counter()
            self.expanded = await super()._retrieve_evidence(candidates, vector, count)
            self.database_ms += (time.perf_counter() - started) * 1000
            return self.expanded

        async def _save_recommendation_result(self, request: Any, result: dict[str, Any]) -> None:
            self.result = result

    schema = 'contextual_multi_' + uuid.uuid4().hex
    connection = await asyncpg.connect(os.environ['DATABASE_URL'])
    pool = None
    sampler = GpuSampler()
    created = False
    observed: list[dict[str, Any]] = []
    before = await public_fingerprint(connection)
    try:
        async with connection.transaction(isolation='repeatable_read'):
            await connection.execute(f'CREATE SCHEMA "{schema}"')
            await connection.execute(f'CREATE TABLE "{schema}".place_embeddings (LIKE public.place_embeddings INCLUDING ALL)')
            await connection.execute(f'INSERT INTO "{schema}".place_embeddings SELECT * FROM public.place_embeddings')
            await connection.execute(f'SET LOCAL search_path TO "{schema}", public')
            for name in ('enrichment', 'contextual'):
                await connection.execute((args.code / f'app/{name}/schema.sql').read_text(encoding='utf-8'))
        created = True
        pool = await asyncpg.create_pool(os.environ['DATABASE_URL'], min_size=1, max_size=1,
            server_settings={'search_path': f'"{schema}", public'}, command_timeout=30)
        snapshot = await pool.fetchval("SELECT md5(string_agg(to_jsonb(p)::text, '' ORDER BY place_id)) FROM place_embeddings p")
        sampler.start()
        target_id = cases['target_place_id']
        fixed_candidates: dict[str, Any] = {}
        active_manifests = {}
        warmed = False
        for pair_index, pair in enumerate(inputs['pairs']):
            record = pair['v2']
            place = ExistingPlace.from_mapping(record['place'])
            actual = await pool.fetchrow('SELECT * FROM place_embeddings WHERE place_id=$1', target_id)
            if ExistingPlace.from_mapping(dict(actual)).source_fingerprint != place.source_fingerprint:
                raise ValueError('저장 장소와 현재 DB 장소가 다릅니다')
            sources = {source['source_id']: SourceDocument.from_mapping(source) for source in record['sources']}
            chunks = [SearchChunk.from_mapping(sources[chunk['source_id']], chunk) for chunk in record['chunks']]
            active = select_active(target_id, chunks + tourapi_chunks(place))
            vectors = await asyncio.to_thread(models.embed, [chunk.embedding_text for chunk in active])
            async with pool.acquire() as private:
                async with private.transaction():
                    await activate_chunks(private, target_id, active, vectors)
            active_manifests[pair['id']] = [chunk.to_dict() for chunk in active]
            queries = [query for query in cases['queries'] if query['pair_id'] == pair['id']]
            for query_index, query in enumerate(queries):
                for repetition in range(args.repetitions):
                    offset = (query_index + pair_index + repetition) % 3
                    for count in (1, 2, 3)[offset:] + (1, 2, 3)[:offset]:
                        runtime = RecordingRuntime(pool, count)
                        now = datetime.now(UTC)
                        payload = {'query': query['query'], 'ranking_mode': 'RERANKED', 'limit': 20,
                                   'requested_at': now.isoformat(), 'filters': {}}
                        request = {'request_id': str(uuid.uuid4()), 'context_version': 1,
                                   'created_at': now, 'payload': json.dumps(payload)}
                        if not warmed:
                            for _ in range(3):
                                await runtime._complete_recommendation(request)
                            warmed = True
                            runtime.database_ms = 0
                        started = time.perf_counter()
                        await runtime._complete_recommendation(request)
                        ended = time.perf_counter()
                        core_ms = (ended - started) * 1000
                        signature = [(candidate['place_id'], candidate['source_version'], candidate['evidence']) for candidate in runtime.candidates]
                        if query['id'] in fixed_candidates and signature != fixed_candidates[query['id']]:
                            raise ValueError('근거 수 비교 중 장소 후보 또는 대표 근거가 달라졌습니다')
                        fixed_candidates[query['id']] = signature
                        pairs = build_pairs(runtime.candidates, runtime.expanded, EvidenceCount(count))
                        if [pair.text for pair in pairs] != models.last_call['texts']:
                            raise ValueError('기록할 근거와 리랭커 실제 입력이 다릅니다')
                        target = next((item for item in runtime.result['items'] if item['place_id'] == target_id), None)
                        rank = target['rank'] if target else None
                        returned = target['evidence_chunks'] if target else []
                        ids = [evidence_id(item, prepared['rows'], query['pair_id']) for item in returned]
                        delivered = [evidence_id(pair.evidence, prepared['rows'], query['pair_id']) for pair in pairs
                                     if runtime.candidates[pair.candidate_index]['place_id'] == target_id]
                        gold = {identifier for identifier, grade in query['relevance'].items() if grade >= 2}
                        lengths = models.input_token_lengths(query['query'], [pair.text for pair in pairs])
                        summary = {'query_id': query['id'], 'pair_id': query['pair_id'], 'kind': query['kind'],
                            'repetition': repetition, 'evidence_count': count, 'target_rank': rank,
                            'selected_span': ids[0] if ids else None, 'returned_spans': ids, 'delivered_spans': delivered,
                            'gold_delivered': bool(gold.intersection(delivered)),
                            'gold_winner_top_5': rank is not None and rank <= 5 and bool(ids) and ids[0] in gold,
                            'gold_any_returned_top_5': rank is not None and rank <= 5 and bool(gold.intersection(ids)),
                            'known_wrong_place_winner': bool(ids) and ids[0] == 'P09-S02',
                            'known_wrong_place_returned': 'P09-S02' in ids,
                            'pair_count': len(pairs), 'input_tokens': sum(lengths), 'max_pair_tokens': max(lengths),
                            'batch_count': models.batch_count(len(pairs)), 'core_elapsed_ms': core_ms,
                            'rerank_http_ms': models.last_call['http_elapsed_ms'], 'database_ms': runtime.database_ms,
                            'worker_dispatch_wait_ms': models.last_call['worker_dispatch_wait_ms'],
                            'gpu_memory': sampler.window(started, ended)}
                        write_new(args.output / f"{query['id']}-n{count}-r{repetition}.json", {
                            'summary': summary, 'query': query['query'], 'result': runtime.result,
                            'pairs': [{'place_id': runtime.candidates[pair.candidate_index]['place_id'],
                                       'evidence': pair.evidence, 'text': pair.text, 'score': score}
                                      for pair, score in zip(pairs, models.last_call['scores'], strict=True)]})
                        observed.append(summary)
                print(json.dumps({'query': query['id'], 'completed': len(observed),
                                  'total': len(cases['queries']) * 3 * args.repetitions}), flush=True)
        write_new(args.output / 'active-manifests.json', active_manifests)
        write_new(args.output / 'candidate-pools.json', fixed_candidates)
        write_new(args.output / 'observations.json', observed)
        write_new(args.output / 'summary.json', summarize(observed))
        write_new(args.output / 'run.json', {
            'status': 'COMPLETED', 'created_at': datetime.now(UTC).isoformat(), 'repetitions': args.repetitions,
            'queries': len(cases['queries']), 'executions': len(observed), 'perplexity_calls': 0,
            'http_calls': models.calls, 'public_before': before, 'snapshot_md5': snapshot,
            'health': models.client.get('/health').json(), 'schema': schema,
            'cases_sha256': sha256(args.cases), 'inputs_sha256': sha256(args.inputs),
            'prepared_sha256': sha256(args.prepared), 'reused_vectors_sha256': sha256(args.vectors),
            'source_files_sha256': {str(path.relative_to(args.code)): sha256(path) for path in args.code.rglob('*.py')},
            'harness_sha256': sha256(Path(__file__)), 'pair_budget': MAX_RERANK_PAIRS,
            'multi_evidence_token_budget': MAX_RERANK_TOKENS, 'tokenizer_max_length': models.tokenizer.model_max_length,
            'candidate_pools_fixed': True, 'warmup_rerank_calls_excluded': 3,
            'model_configuration': {key: os.environ.get(key) for key in ('EMBEDDING_MODEL', 'EMBEDDING_REVISION',
                'RERANK_BATCH_SIZE', 'RERANK_EXECUTION_STRATEGY')},
            'scope': 'v2 only; 9 inputs independently activated; same 449-place snapshot and candidate sets; core worker via local HTTP models; no Spring/Kafka transport',
            'latency_scope': 'cached query vectors; includes worker dispatch, DB, HTTP model round trip and opt-in token counting; excludes raw file writes and post-run scoring; not end-to-end service latency',
            'gpu_scope': 'nvidia-smi whole-device memory sampled every 100ms; shared device, not torch peak allocated; server queue time not independently measured',
        })
    except Exception as exception:
        write_new(args.output / 'failure.json', {'error_type': type(exception).__name__, 'completed': len(observed)})
        raise
    finally:
        sampler.stop()
        write_new(args.output / 'gpu-samples.json', sampler.samples)
        if pool is not None:
            await pool.close()
        if created:
            if not schema.startswith('contextual_multi_') or len(schema) != len('contextual_multi_') + 32:
                raise ValueError('정리할 평가 스키마 이름이 잘못되었습니다')
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        after = await public_fingerprint(connection)
        remaining = await connection.fetchval('SELECT count(*) FROM pg_namespace WHERE nspname=$1', schema)
        write_new(args.output / 'cleanup.json', {'public_after': after, 'public_unchanged': before == after,
                                                'schemas_remaining': remaining})
        await connection.close()
        models.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('code', 'inputs', 'cases', 'prepared', 'vectors', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=3)
    arguments = parser.parse_args()
    if arguments.repetitions < 1:
        parser.error('반복 횟수는 1 이상이어야 합니다')
    sys.path.insert(0, str(arguments.code))
    asyncio.run(main(arguments))
