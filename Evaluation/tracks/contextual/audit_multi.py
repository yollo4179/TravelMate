"""실행 횟수·후보 고정·기준군 일치를 저장 기록만으로 검증한다."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def check_coverage(rows: list[dict[str, Any]], cases: dict[str, Any], repetitions: int) -> None:
    expected = {(query['id'], count, repetition) for query in cases['queries']
                for count in (1, 2, 3) for repetition in range(repetitions)}
    observed = {(row['query_id'], row['evidence_count'], row['repetition']) for row in rows}
    if observed != expected or len(rows) != len(expected):
        raise ValueError('질문·근거 수·반복의 비교 상대가 빠졌거나 중복되었습니다')


def audit(root: Path, cases_path: Path, baseline_path: Path) -> dict[str, Any]:
    run = read_json(root / 'run.json')
    rows = read_json(root / 'observations.json')
    cases = read_json(cases_path)
    if run['status'] != 'COMPLETED' or hashlib.sha256(cases_path.read_bytes()).hexdigest() != run['cases_sha256']:
        raise ValueError('실행 완료 상태 또는 고정 질문 해시가 다릅니다')
    check_coverage(rows, cases, run['repetitions'])
    baseline = {row['query_id']: row for row in read_json(baseline_path)['queries'] if row['version'] == 'v2'}
    pools = read_json(root / 'candidate-pools.json')
    by_variant: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    baseline_checked = 0
    for row in rows:
        key = (row['query_id'], row['evidence_count'])
        by_variant[key].append(row)
        raw = read_json(root / f"{row['query_id']}-n{row['evidence_count']}-r{row['repetition']}.json")
        if raw['summary'] != row:
            raise ValueError('개별 응답과 관찰 집계가 다릅니다')
        fixed_ids = {candidate[0] for candidate in pools[row['query_id']]}
        if len(fixed_ids) != 30 or {pair['place_id'] for pair in raw['pairs']} != fixed_ids:
            raise ValueError('리랭커 입력의 장소 후보가 고정 후보와 다릅니다')
        for pair in raw['pairs']:
            evidence = pair['evidence']
            if evidence and not any(ref['place_id'] == pair['place_id'] and ref['role'] == 'subject' for ref in evidence['place_refs']):
                raise ValueError('subject가 아닌 근거가 리랭커에 전달되었습니다')
        if row['evidence_count'] == 1:
            original = baseline[row['query_id']]
            if row['target_rank'] != original['target_rank_at_20'] or row['selected_span'] != original['selected_span']:
                raise ValueError('단일 근거 기준군이 기존 v2 결과와 다릅니다')
            baseline_checked += 1
    unstable = []
    for key, observations in by_variant.items():
        signatures = {(row['target_rank'], row['selected_span'], tuple(row['returned_spans'])) for row in observations}
        if len(signatures) != 1:
            unstable.append({'query_id': key[0], 'evidence_count': key[1]})
    cleanup = read_json(root / 'cleanup.json')
    if not cleanup['public_unchanged'] or cleanup['schemas_remaining'] != 0:
        raise ValueError('공개 장소 데이터 보존 또는 임시 스키마 정리를 확인하지 못했습니다')
    return {'executions_checked': len(rows), 'baseline_samples_matched': baseline_checked,
            'candidate_pools_checked': len(pools), 'unstable_quality_results': unstable,
            'public_unchanged': True, 'schemas_remaining': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('results', 'cases', 'baseline', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.results, args.cases, args.baseline)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
