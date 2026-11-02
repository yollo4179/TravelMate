"""프롬프트 비교의 요청 불변·실제 모델·비용·검색 기준군을 대조한다."""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from prompt_comparison import verified_plan, read_json
from app.contextual.artifacts import load_record


def audit(root: Path, prior_observations: Path) -> dict[str, Any]:
    plan = verified_plan(root / 'plan.json')
    generation = read_json(root / 'generation-summary.json')
    if not generation['comparison_complete'] or len(generation['results']) != len(plan['pairs']):
        raise ValueError('프롬프트 비교에 누락된 생성 응답이 있습니다')
    replies = set()
    cost = Decimal('0')
    results = []
    planned = {pair['id']: pair for pair in plan['pairs']}
    for pair in generation['results']:
        record_path = Path(pair['candidate_record'])
        _, chunks, record = load_record(record_path)
        request = read_json(record_path.with_name('request.json'))
        if request != planned[pair['id']]['request']:
            raise ValueError('실제 요청이 계획한 요청과 다릅니다')
        comparison = read_json(Path(pair['comparison']))
        if not comparison['actual_model_match'] or not comparison['validation_versions_match']:
            raise ValueError('실제 모델 또는 검증 규칙이 다릅니다')
        raw = read_json(record_path.with_name('raw_response.json'))
        replies.add(raw['id'])
        usage = raw['usage']
        if usage['cost']['currency'] != 'USD':
            raise ValueError('사용량의 통화가 다릅니다')
        cost += Decimal(str(usage['cost']['total_cost']))
        results.append({'id': pair['id'], 'actual_model': raw['model'], 'indexable': len(chunks),
            'excluded': len(record['excluded_chunks']), 'reported_cost_usd': usage['cost']['total_cost'],
            'response_sha256': hashlib.sha256(record_path.with_name('raw_response.json').read_bytes()).hexdigest(),
            'request_sha256': hashlib.sha256(record_path.with_name('request.json').read_bytes()).hexdigest()})
    if len(replies) != len(planned):
        raise ValueError('서로 다른 입력의 응답 ID가 중복되었습니다')
    run = read_json(root / 'retrieval/run.json')
    if run['evidence_per_place'] != 2 or run['variants'] != {'baseline': 'v2', 'candidate': 'v4'}:
        raise ValueError('검색 설정 또는 비교 버전이 다릅니다')
    if run['cases_sha256'] != plan['cases_sha256']:
        raise ValueError('검색 질문이 생성 계획과 다릅니다')
    scores = read_json(root / 'scores.json')
    prior = {row['query_id']: row for row in read_json(prior_observations)
             if row['evidence_count'] == 2 and row['repetition'] == 0}
    baseline = [row for row in scores['queries'] if row['version'] == 'v2']
    for row in baseline:
        if (row['target_rank_at_20'], row['selected_span']) != (prior[row['query_id']]['target_rank'], prior[row['query_id']]['selected_span']):
            raise ValueError('근거 2개 기준군이 앞 실험과 다릅니다')
    cleanup = read_json(root / 'retrieval/cleanup.json')
    if not cleanup['public_unchanged'] or cleanup['schemas_remaining'] != 0:
        raise ValueError('운영 데이터 보존 또는 임시 스키마 정리를 확인하지 못했습니다')
    return {'generation_pairs_verified': len(results), 'unique_provider_responses': len(replies),
        'resumed_invocation_api_calls': generation['api_calls'], 'cached_response_reused': generation['cached_records_reused'],
        'total_v4_generation_responses': len(replies), 'baseline_generation_calls': 0,
        'provider_reported_cost_usd': str(cost), 'results': results, 'evidence_per_place': 2,
        'retrieval_executions': len(run['completed']), 'prior_baseline_queries_matched': len(baseline),
        'public_unchanged': True, 'schemas_remaining': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--prior-observations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    report = audit(arguments.results, arguments.prior_observations)
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}, ensure_ascii=False))
