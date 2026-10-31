"""동일 입력의 보존 응답을 독립 검수용 자료로 준비한다."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / 'embedding-server'))

from app.contextual.artifacts import load_record
from app.contextual.replay import GenerationBaseline


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def response_chunks(path: Path) -> dict[tuple[str, int, int], dict[str, Any]]:
    raw = read_json(path.with_name('raw_response.json'))
    text = ''.join(part['text'] for item in raw['output'] if item.get('type') == 'message'
                   for part in item['content'] if part.get('type') == 'output_text')
    return {(chunk['source_id'], chunk['start'], chunk['end']): chunk for chunk in json.loads(text)['chunks']}


def prepare(batch_path: Path, output: Path) -> Path:
    batch = read_json(batch_path)
    if not batch.get('comparison_complete') or batch.get('failed'):
        raise ValueError('모든 비교 쌍의 재검증이 완료된 배치만 품질 비교에 사용할 수 있습니다')
    if len(batch['comparisons']) != batch['expected_comparisons'] or not batch['comparisons']:
        raise ValueError('기대 비교 쌍과 실제 보고서 수가 다릅니다')
    paths = {}
    original_hashes = {}
    for item in batch['records']:
        path = Path(item['record'])
        record = read_json(path)
        paths[record['request_hash']] = path
        origin = record['revalidated_from']
        for name, expected in origin['file_sha256'].items():
            original = Path(origin['record_path']).with_name(name)
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            if digest != expected:
                raise ValueError('재검증 이후 원본 파일이 변경됐습니다')
            original_hashes[str(original)] = digest
            if name != 'record.json' and hashlib.sha256(path.with_name(name).read_bytes()).hexdigest() != digest:
                raise ValueError('원본과 보존 복사본이 다릅니다')
    pairs = []
    rows = []
    comparisons = [read_json(Path(path)) for path in batch['comparisons']]
    for index, comparison in enumerate(sorted(comparisons, key=lambda item: item['baseline']['request_hash']), 1):
        baseline_path = paths[comparison['baseline']['request_hash']]
        candidate_path = paths[comparison['candidate']['request_hash']]
        baseline = GenerationBaseline.load(baseline_path)
        candidate = GenerationBaseline.load(candidate_path)
        baseline.verify_request(candidate.request)
        if baseline.actual_model != candidate.actual_model:
            raise ValueError('응답 모델이 달라 프롬프트만의 비교를 할 수 없습니다')
        if baseline.record['validation_version'] != candidate.record['validation_version']:
            raise ValueError('양쪽 검증 규칙이 다릅니다')
        left, right = response_chunks(baseline_path), response_chunks(candidate_path)
        if set(left) != set(right):
            raise ValueError('비교할 원문 구간이 다릅니다')
        pair_id = f'P{index:02d}'
        sources = {source.source_id: source for source in baseline.bundle.sources}
        eligible = {}
        for version, path in (('v1', baseline_path), ('v2', candidate_path)):
            _, chunks, _ = load_record(path)
            eligible[version] = {(chunk.source.source_id, chunk.start, chunk.end) for chunk in chunks}
        for ordinal, key in enumerate(sorted(left), 1):
            source_id, start, end = key
            source = sources[source_id]
            rows.append({'id': f'{pair_id}-S{ordinal:02d}', 'pair_id': pair_id, 'source_id': source_id,
                         'source_version': source.source_version, 'start': start, 'end': end,
                         'title': source.title, 'source_url': source.metadata.get('source_url'),
                         'source_type': source.source_type, 'published_at': source.metadata.get('published_at'),
                         'source_text': source.text, 'chunk_text': source.text[start:end],
                         'v1': {**left[key], 'indexable': key in eligible['v1']},
                         'v2': {**right[key], 'indexable': key in eligible['v2']}})
        pairs.append({'id': pair_id, 'baseline_record': str(baseline_path), 'candidate_record': str(candidate_path),
                      'baseline_request_hash': baseline.record['request_hash'],
                      'candidate_request_hash': candidate.record['request_hash'],
                      'model': baseline.actual_model, 'validation_version': baseline.record['validation_version']})
    git_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPOSITORY, text=True).strip()
    prepared = {'created_at': datetime.now(UTC).isoformat(), 'git_sha': git_sha, 'batch_report': str(batch_path),
                'original_file_sha256': original_hashes, 'pairs': pairs, 'rows': rows,
                'api_calls': 0, 'quality_reviewed': False, 'retrieval_evaluated': False}
    output.mkdir(parents=True, exist_ok=False)
    destination = output / 'prepared.json'
    destination.write_text(json.dumps(prepared, ensure_ascii=False, indent=2), encoding='utf-8')
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('--batch-report', type=Path, required=True)
    preparation.add_argument('--output', type=Path, required=True)
    inspection = commands.add_parser('inspect')
    inspection.add_argument('--prepared', type=Path, required=True)
    inspection.add_argument('--sources-only', action='store_true')
    exporting = commands.add_parser('export')
    exporting.add_argument('--prepared', type=Path, required=True)
    exporting.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        destination = prepare(args.batch_report, args.output)
        document = read_json(destination)
        print(json.dumps({'prepared': str(destination), 'pairs': len(document['pairs']),
                          'spans': len(document['rows']), 'original_files': len(document['original_file_sha256'])}))
        return
    if args.command == 'export':
        pairs = []
        for pair in read_json(args.prepared)['pairs']:
            exported = {'id': pair['id']}
            baseline = GenerationBaseline.load(Path(pair['baseline_record']))
            baseline.verify_request(GenerationBaseline.load(Path(pair['candidate_record'])).request)
            for version, key in (('v1', 'baseline_record'), ('v2', 'candidate_record')):
                bundle, chunks, record = load_record(Path(pair[key]))
                exported[version] = {'place': bundle.places[0].to_dict(),
                    'sources': [source.to_dict() for source in bundle.sources],
                    'chunks': [chunk.to_dict() for chunk in chunks], 'request_hash': record['request_hash']}
            pairs.append(exported)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump({'pairs': pairs}, stream, ensure_ascii=False, indent=2)
        print(json.dumps({'pairs': len(pairs), 'output': str(args.output)}))
        return
    for row in read_json(args.prepared)['rows']:
        selected = {key: row[key] for key in ('id', 'source_id', 'start', 'end', 'title', 'chunk_text')}
        if not args.sources_only:
            selected.update(v1=row['v1'], v2=row['v2'])
        print(json.dumps(selected, ensure_ascii=False))


if __name__ == '__main__':
    main()
