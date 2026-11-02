"""보존 v2 요청의 지시문만 바꿔 계획·생성·검색 입력을 기록한다."""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
import uuid

import httpx

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / 'embedding-server'))
from app.contextual.artifacts import collect_bundle, load_record
from app.contextual.prompts import PromptVersion, resolve_prompt
from app.contextual.replay import GenerationBaseline
from app.enrichment.artifacts import write_json


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def request_digest(request: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prepare(prepared_path: Path, cases_path: Path, output: Path) -> Path:
    if output.resolve().is_relative_to((REPOSITORY / 'Evaluation/datasets').resolve()):
        raise ValueError('동결 평가 데이터 안에는 실행 결과를 쓰지 않습니다')
    if output.exists():
        raise ValueError('기존 계획 폴더를 덮어쓰지 않습니다')
    prepared = read_json(prepared_path)
    plans = []
    originals = {}
    for pair in prepared['pairs']:
        path = Path(pair['candidate_record'])
        baseline = GenerationBaseline.load(path)
        if baseline.record['prompt_version'] != PromptVersion.V2 or baseline.record['validation_version'] != 'contextual-validation-v2':
            raise ValueError('동일 검증 규칙의 보존 v2 대조군이 필요합니다')
        candidate = baseline.candidate_request(PromptVersion.V4)
        baseline.verify_request(candidate)
        if baseline.request['instructions'] == candidate['instructions']:
            raise ValueError('비교 지시문이 바뀌지 않았습니다')
        plans.append({'id': pair['id'], 'baseline_record': str(path.resolve()),
            'request': candidate, 'request_sha256': request_digest(candidate),
            'baseline_actual_model': baseline.actual_model, 'request_profile_id': baseline.request_profile_id,
            'unchanged_request_fields': sorted(key for key in candidate if key != 'instructions')})
        for filename in ('record.json', 'request.json', 'sources.json', 'raw_response.json'):
            source = path.with_name(filename)
            originals[str(source.resolve())] = sha256(source)
    if len(plans) != 9:
        raise ValueError('이번 비교는 기존 9개 입력 묶음을 고정합니다')
    output.mkdir(parents=True)
    destination = output / 'plan.json'
    write_json(destination, {'created_at': datetime.now(UTC).isoformat(), 'prompt_version': PromptVersion.V4.value,
        'evidence_per_place': 2, 'prepared_path': str(prepared_path.resolve()), 'prepared_sha256': sha256(prepared_path),
        'cases_path': str(cases_path.resolve()), 'cases_sha256': sha256(cases_path),
        'instructions_sha256': hashlib.sha256(resolve_prompt(PromptVersion.V4).instructions.encode()).hexdigest(),
        'baseline_file_sha256': originals, 'pairs': plans, 'api_calls': 0})
    return destination


def verified_plan(path: Path) -> dict[str, Any]:
    plan = read_json(path)
    if hashlib.sha256(resolve_prompt(plan['prompt_version']).instructions.encode()).hexdigest() != plan['instructions_sha256']:
        raise ValueError('계획 이후 지시문이 바뀌었습니다')
    for filename, expected in plan['baseline_file_sha256'].items():
        if sha256(Path(filename)) != expected:
            raise ValueError('계획 이후 대조군 원본이 바뀌었습니다')
    for key in ('prepared', 'cases'):
        if sha256(Path(plan[key + '_path'])) != plan[key + '_sha256']:
            raise ValueError('계획 이후 입력 또는 질문이 바뀌었습니다')
    for pair in plan['pairs']:
        baseline = GenerationBaseline.load(Path(pair['baseline_record']))
        baseline.verify_request(pair['request'])
        if request_digest(pair['request']) != pair['request_sha256']:
            raise ValueError('미리보기 요청 해시가 다릅니다')
        if pair['request']['instructions'] != resolve_prompt(plan['prompt_version']).instructions:
            raise ValueError('미리보기 요청의 지시문이 다릅니다')
    return plan


def read_api_key(path: Path) -> str:
    text = path.read_text(encoding='utf-8-sig').strip()
    matches = set(re.findall(r'\bpplx-[A-Za-z0-9_-]{20,}\b', text))
    if len(matches) != 1:
        raise ValueError('명시한 키 파일에서 API 키 하나를 확인해야 합니다')
    return matches.pop()


async def generate(plan_path: Path, key_path: Path) -> Path:
    plan = verified_plan(plan_path)
    output = plan_path.parent
    summary_path = output / 'generation-summary.json'
    if summary_path.exists():
        raise ValueError('이미 완료 또는 중단된 생성 기록이 있습니다. 자동 유료 재시도하지 않습니다')
    api_key = read_api_key(key_path)
    calls = 0
    results = []

    async def count_request(request: httpx.Request) -> None:
        nonlocal calls
        calls += 1
        if calls > len(plan['pairs']):
            raise ValueError('계획한 호출 수를 초과했습니다')
        write_json(output / 'http-attempts' / f'{uuid.uuid4()}.json', {
            'created_at': datetime.now(UTC).isoformat(), 'request_sha256': request_digest(json.loads(request.content)),
            'status': 'attempted', 'note': '전송 시도 기록이며 과금 여부는 실제 응답 usage로 확인한다.'})

    async with httpx.AsyncClient(event_hooks={'request': [count_request]}) as client:
        for pair in plan['pairs']:
            baseline = GenerationBaseline.load(Path(pair['baseline_record']))
            before = calls
            result_path = await collect_bundle(baseline.bundle, baseline.settings(api_key, 180), output / 'generation', client,
                prompt_version=plan['prompt_version'], prepared_request=pair['request'], request_profile_id=baseline.request_profile_id)
            record = read_json(result_path)
            comparison_path = baseline.write_report(result_path, output_directory=output / 'comparisons' / pair['id'])
            comparison = read_json(comparison_path)
            result = {'id': pair['id'], 'baseline_record': pair['baseline_record'], 'candidate_record': str(result_path.resolve()),
                'comparison': str(comparison_path.resolve()), 'status': record['status'],
                'actual_model_match': comparison['actual_model_match'], 'api_calls': calls - before,
                'indexable_chunks': len(record.get('chunks', [])), 'excluded_chunks': len(record.get('excluded_chunks', [])),
                'usage': record.get('usage')}
            if record.get('http_status'):
                result['http_status'] = record['http_status']
            results.append(result)
            print(json.dumps({key: result[key] for key in ('id', 'status', 'actual_model_match', 'api_calls')}, ensure_ascii=False), flush=True)
            if record['status'] != 'COLLECTED' or comparison['actual_model_match'] is not True:
                break
    verified_plan(plan_path)
    complete = len(results) == len(plan['pairs']) and all(
        row['status'] == 'COLLECTED' and row['actual_model_match'] is True for row in results)
    write_json(summary_path, {'created_at': datetime.now(UTC).isoformat(), 'comparison_complete': complete,
        'plan_sha256': sha256(plan_path), 'key_source': 'explicit_key_file', 'api_calls': calls,
        'cached_records_reused': sum(row['api_calls'] == 0 for row in results),
        'baseline_calls': 0, 'results': results})
    return summary_path


def export(plan_path: Path) -> Path:
    plan = verified_plan(plan_path)
    summary = read_json(plan_path.with_name('generation-summary.json'))
    if not summary['comparison_complete']:
        raise ValueError('실제 모델·검증 규칙이 맞는 9쌍의 생성 완료가 필요합니다')
    if any(plan_path.with_name(name).exists() for name in ('retrieval-inputs.json', 'prepared-comparison.json')):
        raise ValueError('기존 검색·검수 입력을 덮어쓰지 않습니다')
    pairs = []
    for row in summary['results']:
        exported = {'id': row['id']}
        for name, field in (('v2', 'baseline_record'), ('v4', 'candidate_record')):
            bundle, chunks, record = load_record(Path(row[field]))
            exported[name] = {'place': bundle.places[0].to_dict(), 'sources': [source.to_dict() for source in bundle.sources],
                'chunks': [chunk.to_dict() for chunk in chunks], 'request_hash': record['request_hash']}
        pairs.append(exported)
    destination = plan_path.with_name('retrieval-inputs.json')
    write_json(destination, {'pairs': pairs})
    write_json(plan_path.with_name('prepared-comparison.json'), prepared_comparison(plan_path))
    return destination


def prepared_comparison(plan_path: Path) -> dict[str, Any]:
    plan = verified_plan(plan_path)
    summary_path = plan_path.with_name('generation-summary.json')
    summary = read_json(summary_path)
    if not summary['comparison_complete']:
        raise ValueError('검수 입력을 만들려면 9쌍 생성이 완료돼야 합니다')
    originals = read_json(Path(plan['prepared_path']))
    responses = {}
    indexable = {}
    for pair in summary['results']:
        path = Path(pair['candidate_record'])
        _, chunks, _ = load_record(path)
        raw = read_json(path.with_name('raw_response.json'))
        text = ''.join(part['text'] for item in raw['output'] if item.get('type') == 'message'
                       for part in item['content'] if part.get('type') == 'output_text')
        responses[pair['id']] = {(chunk['source_id'], chunk['start'], chunk['end']): chunk
                                 for chunk in json.loads(text)['chunks']}
        indexable[pair['id']] = {(chunk.source.source_id, chunk.start, chunk.end) for chunk in chunks}
    rows = []
    for row in originals['rows']:
        key = (row['source_id'], row['start'], row['end'])
        candidate = responses[row['pair_id']][key]
        rows.append({**{name: value for name, value in row.items() if name not in ('v1', 'v2')},
            'v2': row['v2'], 'v4': {**candidate, 'indexable': key in indexable[row['pair_id']]}})
    return {'rows': rows, 'pairs': summary['results'], 'generation_summary_sha256': sha256(summary_path), 'evidence_per_place': 2}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('--prepared', type=Path, required=True)
    preparation.add_argument('--cases', type=Path, required=True)
    preparation.add_argument('--output', type=Path, required=True)
    generation = commands.add_parser('generate')
    generation.add_argument('--plan', type=Path, required=True)
    generation.add_argument('--key-file', type=Path, required=True)
    exporting = commands.add_parser('export')
    exporting.add_argument('--plan', type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == 'prepare':
        path = prepare(arguments.prepared, arguments.cases, arguments.output)
        print(json.dumps({'plan': str(path), 'pairs': len(read_json(path)['pairs']), 'api_calls': 0}))
    elif arguments.command == 'generate':
        summary_path = asyncio.run(generate(arguments.plan, arguments.key_file))
        print(str(summary_path))
        raise SystemExit(0 if read_json(summary_path)['comparison_complete'] else 1)
    else:
        print(str(export(arguments.plan)))
