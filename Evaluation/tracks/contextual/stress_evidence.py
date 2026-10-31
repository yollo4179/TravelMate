"""실측 후보 텍스트를 반복해 30/60/90쌍의 모델 부하만 측정한다."""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import time

from multi_evidence import RecordingModels, GpuSampler, distribution, sha256
from retrieve import write_new


async def main(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError('부하 실험 결과를 덮어쓰지 않습니다')
    args.output.mkdir(parents=True)
    observations = json.loads((args.source / 'observations.json').read_text(encoding='utf-8'))
    selected = max((row for row in observations if row['evidence_count'] == 1 and row['repetition'] == 0),
                   key=lambda row: row['input_tokens'])
    record = json.loads((args.source / f"{selected['query_id']}-n1-r0.json").read_text(encoding='utf-8'))
    texts = [pair['text'] for pair in record['pairs']]
    if len(texts) != 30:
        raise ValueError('부하 실험 기준 후보는 30개여야 합니다')
    models = RecordingModels(args.vectors)
    sampler = GpuSampler()
    sampler.start()
    rows = []
    try:
        from app.contextual.ranking import MAX_RERANK_PAIRS, MAX_RERANK_TOKENS
        for count in (1, 2, 3):
            await asyncio.to_thread(models.rerank, record['query'], texts * count)
        for repetition in range(3):
            for count in (1, 2, 3)[repetition:] + (1, 2, 3)[:repetition]:
                inputs = [text for text in texts for _ in range(count)]
                lengths = models.input_token_lengths(record['query'], inputs)
                if len(inputs) > MAX_RERANK_PAIRS or sum(lengths) > MAX_RERANK_TOKENS:
                    raise ValueError('부하 실험 입력이 예산을 초과했습니다')
                started = time.perf_counter()
                await asyncio.to_thread(models.rerank, record['query'], inputs)
                ended = time.perf_counter()
                rows.append({'repetition': repetition, 'pair_count': len(inputs), 'tokens': sum(lengths),
                    'max_pair_tokens': max(lengths), 'batch_count': models.batch_count(len(inputs)),
                    'http_elapsed_ms': models.last_call['http_elapsed_ms'], 'gpu_memory': sampler.window(started, ended)})
        write_new(args.output / 'results.json', rows)
        write_new(args.output / 'summary.json', {str(count): distribution([
            row['http_elapsed_ms'] for row in rows if row['pair_count'] == count]) for count in (30, 60, 90)})
        write_new(args.output / 'run.json', {'created_at': datetime.now(UTC).isoformat(),
            'source_query': selected['query_id'], 'source_observations_sha256': sha256(args.source / 'observations.json'),
            'harness_sha256': sha256(Path(__file__)), 'local_rerank_calls': models.calls['rerank'], 'perplexity_calls': 0,
            'scope': 'load only; repeat real candidate texts; not distinct chunk retrieval or quality measurement',
            'repetitions_per_size': 3, 'warmup_calls_excluded': 3})
    finally:
        sampler.stop()
        write_new(args.output / 'gpu-samples.json', sampler.samples)
        models.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'vectors', 'output', 'code'):
        parser.add_argument('--' + name, type=Path, required=True)
    arguments = parser.parse_args()
    sys.path.insert(0, str(arguments.code))
    asyncio.run(main(arguments))
