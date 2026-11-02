"""고정 통제 원문·보존 P09를 최대 2회만 Sonar로 생성한다."""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
import uuid
from typing import Any

import httpx

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'embedding-server'))
from app.contextual.agent import request_payload
from app.contextual.artifacts import SourceBundle,collect_bundle,load_record
from app.contextual.contracts import SplitterVersion
from app.contextual.input_format import InputVersion
from app.contextual.prompts import PromptVersion
from app.enrichment.agent import AgentSettings
from app.enrichment.artifacts import write_json
from app.enrichment.contracts import ExistingPlace
from Evaluation.tracks.contextual.prompt_comparison import read_api_key,request_digest,sha256


def prepare(baseline: Path, output: Path) -> Path:
    if output.exists():
        raise ValueError('기존 실행 폴더는 덮어쓰지 않습니다')
    bundle,_,_=load_record(baseline)
    controls=[
        ('mixed-supporting','A공원은 야경이 아름답고, 관람 후 B공원으로 걸어갈 수 있다.'),
        ('primary-route','A공원에서 계단을 내려가 B공원까지 걸어갔다.'),
        ('b-parking','B공원 주차장은 무료였고 주말에는 혼잡했다.'),
        ('blocked-route','A공원에서 B공원으로 이동하려 했지만 공사로 길이 막혀 돌아왔다.'),
    ]
    controlled=SourceBundle.from_mapping({'places':[ExistingPlace(101,'A공원').to_dict(),ExistingPlace(202,'B공원').to_dict()],
        'sources':[{'source_type':'review','title':identifier,'text':text,
            'metadata':{'source_url':'https://example.org/v7/'+identifier,'capture_scope':'full_text'}} for identifier,text in controls]})
    pairs=[]
    for identifier,current in [('CONTROL',controlled),('P09',bundle)]:
        request=request_payload(current.places,current.sources,AgentSettings(model='perplexity/sonar'),
            prompt_version=PromptVersion.V7,input_version=InputVersion.EXPLICIT,splitter_version=SplitterVersion.SENTENCE)
        pairs.append({'id':identifier,'bundle':current.to_dict(),'request':request,'request_sha256':request_digest(request)})
    output.mkdir(parents=True)
    path=output/'plan.json'
    write_json(path,{'created_at':datetime.now(UTC).isoformat(),'maximum_new_calls':2,'pairs':pairs,
        'baseline_record':str(baseline.resolve()),'baseline_file_sha256':{name:sha256(baseline.with_name(name))
            for name in ('record.json','request.json','sources.json','raw_response.json')},
        'frozen_expectations':{'mixed-supporting':{'subject_ids':[101],'mentioned_ids':[202],'kind':'landscape','importance':'supporting','origin':101,'destination':202},
            'primary-route':{'kind':'movement','importance':'primary','origin':101,'destination':202},
            'b-parking':{'subject_ids':[202],'kind':'facility','relation_count':0},
            'blocked-route':'귀속 보류를 허용하되 관계를 만들면 공사·막힘·돌아옴을 근거와 문맥에 보존해야 한다.',
            'P09-view-owner':{'source_id':'68ef479e-6b88-5636-bfdf-c096fc287b89','start':573,'end':588,'forbidden_subject_ids':[394]},
            'P09-parking':{'source_id':'68ef479e-6b88-5636-bfdf-c096fc287b89','start':109,'end':125,'required_subject_id':394}},
        'production_database_writes':0})
    return path


async def execute(plan_path: Path,key_file: Path, *, transport: httpx.AsyncBaseTransport | None = None) -> Path:
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    output=plan_path.parent
    if (output/'http-attempts').exists() or (output/'generation-summary.json').exists():
        raise ValueError('기존 호출 기록이 있어 자동 재시도하지 않습니다')
    if plan['maximum_new_calls']!=2 or len(plan['pairs'])!=2:
        raise ValueError('호출 상한이 다릅니다')
    baseline=Path(plan['baseline_record'])
    for name,expected in plan['baseline_file_sha256'].items():
        if sha256(baseline.with_name(name))!=expected:
            raise ValueError('대조군 원본이 바뀌었습니다')
    settings=AgentSettings(model='perplexity/sonar',api_key=read_api_key(key_file),timeout_seconds=180)
    for pair in plan['pairs']:
        bundle=SourceBundle.from_mapping(pair['bundle'])
        expected=request_payload(bundle.places,bundle.sources,settings,prompt_version=PromptVersion.V7,
            input_version=InputVersion.EXPLICIT,splitter_version=SplitterVersion.SENTENCE)
        if expected!=pair['request'] or request_digest(expected)!=pair['request_sha256']:
            raise ValueError('고정 요청과 다릅니다')
    calls=0
    async def before(request: httpx.Request) -> None:
        nonlocal calls
        if calls>=2:
            raise ValueError('유료 호출 상한 초과')
        calls+=1
        write_json(output/'http-attempts'/f'{uuid.uuid4()}.json',{'number':calls,'request_sha256':request_digest(json.loads(request.content))})
    async def error_response(response: httpx.Response) -> None:
        if response.is_error:
            body=(await response.aread()).decode('utf-8',errors='replace')
            body=re.sub(r'pplx-[A-Za-z0-9_-]+','[REDACTED]',body.replace(settings.api_key,'[REDACTED]'))
            write_json(output/'http-errors'/f'{uuid.uuid4()}.json',{'status':response.status_code,'body':body[:4096],
                'content_type':response.headers.get('content-type'),'request_id':response.headers.get('x-request-id')})
    results=[]
    cost=Decimal('0')
    error_type=None
    try:
        async with httpx.AsyncClient(transport=transport,event_hooks={'request':[before],'response':[error_response]}) as client:
            for pair in plan['pairs']:
                bundle=SourceBundle.from_mapping(pair['bundle'])
                path=await collect_bundle(bundle,settings,output/'g',client,prompt_version=PromptVersion.V7,
                    prepared_request=pair['request'],input_version=InputVersion.EXPLICIT,splitter_version=SplitterVersion.SENTENCE)
                record=json.loads(path.read_text(encoding='utf-8'))
                raw_path=path.with_name('raw_response.json')
                raw=json.loads(raw_path.read_text(encoding='utf-8')) if raw_path.exists() else {}
                amount=raw.get('usage',{}).get('cost',{}).get('total_cost',0)
                cost+=Decimal(str(amount))
                result={'id':pair['id'],'record':str(path.resolve()),'status':record['status'],'actual_model':raw.get('model'),
                    'indexable':len(record.get('chunks',[])),'excluded':len(record.get('excluded_chunks',[])),
                    'provider_status':raw.get('status'),'cost_usd':str(amount),'error_type':record.get('error_type')}
                results.append(result)
                print(json.dumps({key:value for key,value in result.items() if key!='record'},ensure_ascii=False),flush=True)
                if record['status']!='COLLECTED' or raw.get('model')!='perplexity/sonar':
                    break
    except Exception as exception:
        error_type=type(exception).__name__
    destination=output/'generation-summary.json'
    write_json(destination,{'api_calls':calls,'plan_sha256':sha256(plan_path),'provider_reported_cost_usd':str(cost),
        'results':results,'error_type':error_type,'all_collected':error_type is None and len(results)==2 and all(row['status']=='COLLECTED' and row['actual_model']=='perplexity/sonar' for row in results),
        'production_database_writes':0})
    return destination


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    preparation=commands.add_parser('prepare')
    preparation.add_argument('--baseline-record',type=Path,required=True)
    preparation.add_argument('--output',type=Path,required=True)
    execution=commands.add_parser('generate')
    execution.add_argument('--plan',type=Path,required=True)
    execution.add_argument('--key-file',type=Path,required=True)
    execution.add_argument('--execute',action='store_true',required=True)
    args=parser.parse_args()
    if args.command=='prepare':
        print(prepare(args.baseline_record,args.output))
        return
    result=asyncio.run(execute(args.plan,args.key_file))
    print(result)
    raise SystemExit(0 if json.loads(result.read_text(encoding='utf-8'))['all_collected'] else 1)


if __name__=='__main__':
    main()
