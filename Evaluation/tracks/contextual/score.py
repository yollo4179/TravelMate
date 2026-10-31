"""목표 장소의 순위와 원문 구간 일치를 나눠 고정 질문의 결과를 집계한다."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def evidence_id(evidence: dict[str, Any] | None, rows: list[dict[str, Any]], pair_id: str) -> str | None:
    if not evidence:
        return None
    span = evidence['source_span']
    return next((row['id'] for row in rows if row['pair_id'] == pair_id
        and row['source_id'] == evidence['source_id'] and row['source_version'] == evidence['source_version']
        and row['start'] == span['start'] and row['end'] == span['end']), None)


def observations(directory: Path, cases: dict[str, Any], prepared: dict[str, Any]) -> list[dict[str, Any]]:
    observed = []
    for query in cases['queries']:
        for version in ('v1', 'v2'):
            result = read_json(directory / f"{query['id']}-{version}.json")
            if any(result[field] != expected for field, expected in (
                ('query_id', query['id']), ('version', version), ('pair_id', query['pair_id']),
                ('query', query['query']), ('kind', query['kind']))):
                raise ValueError('고정 질문과 실행 결과의 식별자가 다릅니다')
            items = result['result']['items']
            if result['result']['status'] != 'COMPLETED' or len({item['place_id'] for item in items}) != len(items):
                raise ValueError('완료되지 않았거나 장소가 중복된 결과입니다')
            target = next((item for item in items if item['place_id'] == cases['target_place_id']), None)
            semantic = next(((rank, item) for rank, item in enumerate(result['semantic_candidates'], 1)
                             if item['place_id'] == cases['target_place_id']), None)
            evidence = target['evidence_chunks'][0] if target and target['evidence_chunks'] else None
            selected = evidence_id(evidence, prepared['rows'], query['pair_id'])
            observed.append({'query_id': query['id'], 'version': version, 'kind': query['kind'],
                'target_rank_at_20': target['rank'] if target else None,
                'target_semantic_rank_at_30': semantic[0] if semantic else None,
                'selected_span': selected, 'gold_span_hit': query['relevance'].get(selected, 0) >= 2,
                'forbidden_span_exposed': selected in query.get('forbidden_evidence', []),
                'caution_span_exposed': selected in query.get('caution_evidence', []),
                'rerank_score': target['rerank_score'] if target else None})
    return observed


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError('집계 대상 질문이 없습니다')
    count = len(rows)
    return {'queries': count,
        'target_semantic_hit_at_30': sum(row['target_semantic_rank_at_30'] is not None for row in rows),
        'target_top_1': sum(row['target_rank_at_20'] == 1 for row in rows),
        'target_top_5': sum(row['target_rank_at_20'] is not None and row['target_rank_at_20'] <= 5 for row in rows),
        'target_top_10': sum(row['target_rank_at_20'] is not None and row['target_rank_at_20'] <= 10 for row in rows),
        'target_mrr_at_20': sum(1 / row['target_rank_at_20'] if row['target_rank_at_20'] else 0 for row in rows) / count,
        'target_and_gold_span_at_5': sum(row['gold_span_hit'] and row['target_rank_at_20'] is not None
                                       and row['target_rank_at_20'] <= 5 for row in rows)}


def score(args: argparse.Namespace) -> dict[str, Any]:
    cases = read_json(args.cases)
    prepared = read_json(args.prepared)
    run = read_json(args.results / 'run.json')
    cleanup = read_json(args.results / 'cleanup.json')
    if run['cases_sha256'] != hashlib.sha256(args.cases.read_bytes()).hexdigest():
        raise ValueError('실행 이후 질문 파일이 변경되었습니다')
    expected = {(query['id'], version) for query in cases['queries'] for version in ('v1', 'v2')}
    completed = {(row['query_id'], row['version']) for row in run['completed']}
    if run['status'] != 'COMPLETED' or completed != expected or len(run['completed']) != len(expected):
        raise ValueError('일부 질문의 비교 상대가 없거나 중복되었습니다')
    observed = observations(args.results, cases, prepared)
    supported = [row for row in observed if row['kind'] == 'supported']
    review = read_json(args.review)
    if {row['id'] for row in review['rows']} != {row['id'] for row in prepared['rows']}:
        raise ValueError('검수 구간과 실행 원문 구간이 다릅니다')
    return {'cases_sha256': run['cases_sha256'], 'perplexity_calls': run['perplexity_calls'],
        'public_unchanged': cleanup['public_unchanged'], 'schemas_remaining': cleanup['schemas_remaining'],
        'supported': {version: aggregate([row for row in supported if row['version'] == version]) for version in ('v1', 'v2')},
        'supported_without_ambiguous_Q10': {version: aggregate([row for row in supported if row['version'] == version and row['query_id'] != 'Q10']) for version in ('v1', 'v2')},
        'review_flags': {version: dict(Counter(flag for row in review['rows'] for flag in row[version])) for version in ('v1', 'v2')},
        'queries': observed,
        'interpretation': '단일 대상 장소의 순위·구간 선택 진단. 다른 장소의 적합성은 판정하지 않았으므로 전체 검색 정확도·재현율이나 운영 end-to-end 성능으로 표시하지 않는다.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    summary = score(arguments)
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    print(json.dumps({key: summary[key] for key in ('supported', 'review_flags', 'public_unchanged')}, ensure_ascii=False))
