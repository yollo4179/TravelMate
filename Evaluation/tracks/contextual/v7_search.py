"""실제 BGE·PostgreSQL·리랭커에서 단계별 근거 도달 여부를 검사한다. 운영 DB는 사용하지 않는다."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path, PureWindowsPath
import sys
import time
from types import SimpleNamespace
from typing import Any
import uuid
from unittest.mock import patch

import asyncpg
import httpx

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'embedding-server'))
from app.contextual.artifacts import load_record
from app.contextual.contracts import SearchChunk,SplitterVersion
from app.contextual.pipeline import normalize_source,select_active,index_embedding_inputs
from app.contextual.repository import activate_chunks
from app.contextual.ranking import EvidenceCount,build_pairs,rank_places
from app.contextual.observation_search import ObservationFilter
from app.contextual.review import approval_document
from app.enrichment.contracts import ExistingPlace
from app.enrichment.artifacts import write_json
from app.enrichment.repository import ensure_schema


def portable(path: str,root: Path) -> Path:
    prefix=PureWindowsPath('C:/ssafy/Travelmate/Evaluation/runs/contextual/v7-integration-v1/20261101-01')
    return root/Path(*PureWindowsPath(path).relative_to(prefix).parts)


def reviewed_inputs(root: Path) -> tuple[dict[int,ExistingPlace],list[SearchChunk],SearchChunk,dict[str,Any]]:
    summary=json.loads((root/'sonar/generation-summary.json').read_text(encoding='utf-8'))
    places={}
    approved=[]
    supporting=None
    decisions=[]
    for result in summary['results']:
        path=portable(result['record'],root)
        bundle,chunks,record=load_record(path)
        places.update({place.place_id:place for place in bundle.places})
        selected=chunks
        # P09는 의미 검수한 원문 위치만 승인한다. 번호 대신 원문으로 고정해 경계 변화에 기대지 않는다.
        if result['id']=='P09':
            anchors=('청담도로 공원주차장은 무료라서','주차장에 도착하면 정자 하나가 보여요','벚꽃나무쪽에 보면 흙길이 보여요',
                '**청담도로공원주차장**','다행히도 청담도로공원이 있다.','주차장은 한 15~20대 정도고 화장실이 있다.',
                '무척 낡은 화장실이지만 휴지도 있다.','80년대 체험이 가능한 화장실.')
            selected=[chunk for chunk in chunks if any(anchor in chunk.chunk_text for anchor in anchors)]
            if len(selected)!=8:
                raise ValueError('P09 검수 원문과 현재 후보 수가 다릅니다')
        decisions.append({'id':result['id'],'validated_candidates':len(chunks),'approved':len(selected),
                          'withheld_valid':len(chunks)-len(selected),'reviewer':'버전을 아는 에이전트의 개발 검수'})
        write_json(root/f'approval-{result["id"]}.json',approval_document(path,[chunk.chunk_id for chunk in selected],'에이전트 원문·귀속 검수'))
        approved.extend(selected)
        if result['id']=='CONTROL':
            raw=json.loads(path.with_name('raw_response.json').read_text(encoding='utf-8'))
            document=json.loads(''.join(part['text'] for item in raw['output'] if item.get('type')=='message'
                for part in item.get('content',[]) if part.get('type')=='output_text'))
            source=next(source for source in bundle.sources if source.title=='mixed-supporting')
            row=deepcopy(next(row for row in document['chunks'] if row['source_id']==source.source_id))
            relation=row['relations'][0]
            quote=relation['evidence']['quote']
            if source.text.count(quote)!=1:
                raise ValueError('위치 진단은 원문에 정확히 한 번 있는 인용만 사용합니다')
            original=deepcopy(relation['evidence'])
            relation['evidence'].update(start=source.text.index(quote),end=source.text.index(quote)+len(quote))
            supporting=SearchChunk(source,row['start'],row['end'],row['context_text'],row['place_refs'],
                {'provider':'diagnostic-only','model':raw['model'],'prompt_version':record['prompt_version'],
                 'response_id':raw['id'],'processing':'unique-exact-quote-alignment-diagnostic-v1'},row['entities'],[],
                SplitterVersion.SENTENCE,row['content_kind'],row['relations'])
            write_json(root/'alignment-diagnostic.json',{'original_evidence':original,'diagnostic_evidence':relation['evidence'],
                'source_id':source.source_id,'request_record_unchanged':True,'automatic_validation_rules_unchanged':True,
                'note':'서버 수정이 아니다. 같은 응답의 인용 위치만 맞춘 별도 감독 진단이며 모델 자동 성공으로 세지 않는다.'})
    if supporting is None:
        raise ValueError('보조 관계 진단 자료가 없습니다')
    return places,approved,supporting,{'decisions':decisions,'strict_approved_chunks':len(approved)}


def distractors() -> tuple[dict[int,ExistingPlace],list[SearchChunk]]:
    places={}
    chunks=[]
    for index in range(1,41):
        identifier=1000+index
        name=f'연결공원{index:02d}'
        place=ExistingPlace(identifier,name)
        quote='B공원까지 차량으로만 이동할 수 있으며 도보 통행은 금지된다.'
        text=f'{name}의 주차장은 넓고 화장실과 벤치가 있으며, '+quote
        source=normalize_source({'source_type':'review','title':name+' 합성 방해 사례','text':text,
            'metadata':{'source_url':f'https://example.org/v7-negative/{index}','capture_scope':'full_text'}})
        refs=[{'place_id':identifier,'role':'subject'},{'place_id':202,'role':'mentioned'}]
        relation={'type':'movement','importance':'supporting','origin':{'place_id':identifier,'name':name},
            'destination':{'place_id':202,'name':'B공원'},'conditions':[{'kind':'other','quote':'도보 통행은 금지된다'}],
            'evidence':{'start':text.index(quote),'end':len(text),'quote':quote}}
        chunks.append(SearchChunk(source,0,len(text),f'{name}의 시설과 B공원으로는 차량 이동만 가능하다는 내용이다.',
            refs,{'provider':'synthetic-negative-fixture','prompt_version':'retrieval-stress-v1'},[],[],
            SplitterVersion.SENTENCE,'facility',[relation]))
        places[identifier]=place
    return places,chunks


async def run(root: Path,base_url: str) -> Path:
    host=os.environ['PGHOST'];database=os.environ['PGDATABASE']
    if not host.startswith('tm-v7-eval-') or not database.startswith('contextual_v7_eval'):
        raise ValueError('폐기용 DB만 사용할 수 있습니다')
    if (root/'search-summary.json').exists() or (root/'search-plan.json').exists():
        raise ValueError('기존 검색 검증은 덮어쓰거나 자동 재실행하지 않습니다')
    places,approved,supporting,review=reviewed_inputs(root)
    negative_places,negative=distractors();places.update(negative_places)
    questions=[
        {'id':'mixed-landscape','query':'야경이 아름다운 공원','filters':{'content_kinds':['landscape']},'target_place':101,'target_chunk':supporting.chunk_id},
        {'id':'supporting-to-b','query':'B공원으로 걸어서 갈 수 있는 곳','filters':{'destination_place_id':202,'relation_importance':['supporting']},'target_place':101,'target_chunk':supporting.chunk_id},
        {'id':'supporting-from-a','query':'A공원에서 관람 후 걸어서 갈 수 있는 공원','filters':{'origin_place_id':101,'relation_importance':['supporting']},'target_place':202,'target_chunk':supporting.chunk_id},
        {'id':'primary-stairs','query':'B공원으로 계단을 내려가 걸어갈 수 있는 곳','filters':{'destination_place_id':202,'relation_importance':['primary']},'target_place':101,
            'target_chunk':next(chunk.chunk_id for chunk in approved if chunk.source.title=='primary-route')},
        {'id':'real-parking','query':'청담도로공원 주차장은 무료인가요','filters':{'content_kinds':['facility']},'target_place':394,
            'target_chunk':next(chunk.chunk_id for chunk in approved if '청담도로 공원주차장은 무료라서' in chunk.chunk_text)},
        {'id':'real-view-regression','query':'한강 야경이 아름다운 청담도로공원','filters':{'content_kinds':['landscape']},'target_place':394,'target_chunk':None},
    ]
    write_json(root/'search-plan.json',{'review':review,'questions':questions,'negative_fixtures':[chunk.to_dict() for chunk in negative],
        'phases':['strict-v7','diagnostic-unique-quote-alignment'],'evidence_per_place':2,'candidate_limit':30,
        'embedding_input':'context_text+chunk_text','importance_only_embedding':False,
        'diagnostic_is_not_model_success':True,'production_database_writes':0})
    cache={};http_calls={'embed':0,'rerank':0}
    async with httpx.AsyncClient(base_url=base_url,timeout=180,trust_env=False) as client:
        health=(await client.get('/health')).json()
        async def embed(texts: list[str]) -> list[list[float]]:
            missing=list(dict.fromkeys(text for text in texts if text not in cache))
            if missing:
                response=await client.post('/embed',json={'texts':missing});response.raise_for_status()
                values=response.json()['embeddings']
                if len(values)!=len(missing) or any(len(value)!=1024 for value in values):
                    raise ValueError('임베딩 계약이 다릅니다')
                cache.update(zip(missing,values));http_calls['embed']+=1
            return [cache[text] for text in texts]
        query_vectors=await embed([question['query'] for question in questions])
        import_context={'app.embedder':SimpleNamespace(embedder=SimpleNamespace(device='http-existing-model')),
                        'app.reranker':SimpleNamespace(reranker=SimpleNamespace(device='http-existing-model'))}
        with patch.dict(sys.modules,import_context):
            runtime_module=importlib.import_module('app.kafka_runtime')
        admin=await asyncpg.connect(host=host,user='postgres',database=database)
        all_results=[]
        try:
            for phase in ('strict-v7','diagnostic-unique-quote-alignment'):
                schema='v7_search_'+uuid.uuid4().hex
                await admin.execute(f'CREATE SCHEMA {schema}')
                pool=await asyncpg.create_pool(host=host,user='postgres',database=database,min_size=1,max_size=3,
                    server_settings={'search_path':schema+',public'})
                try:
                    await pool.execute((ROOT/'Docker/search-init/01-search-schema.sql').read_text(encoding='utf-8'))
                    await ensure_schema(pool)
                    chunks=approved+negative+([supporting] if phase!='strict-v7' else [])
                    for place in places.values():
                        mapping=place.to_dict();columns=list(mapping)
                        await pool.execute('INSERT INTO place_embeddings('+','.join(columns)+',source_version,latest_seen_version) VALUES('
                            +','.join(f'${index+1}' for index in range(len(columns)))+',1,1)',*mapping.values())
                    selections={place_id:select_active(place_id,chunks) for place_id in places}
                    plans={place_id:index_embedding_inputs(places[place_id],selected) for place_id,selected in selections.items()}
                    await embed([text for texts,_ in plans.values() for text in texts])
                    async with pool.acquire() as connection:
                        async with connection.transaction():
                            for place_id,selected in selections.items():
                                texts,primary=plans[place_id];vectors=[cache[text] for text in texts]
                                await activate_chunks(connection,place_id,selected,vectors[:len(selected)])
                                await connection.execute('UPDATE place_embeddings SET embedding=$2::vector WHERE place_id=$1',place_id,
                                    '['+','.join(map(str,vectors[primary]))+']')
                    runtime=object.__new__(runtime_module.KafkaRuntime);runtime.database_pool=pool
                    for question,vector in zip(questions,query_vectors):
                        started=time.perf_counter();vector_text='['+','.join(map(str,vector))+']'
                        filters={'observation':question['filters']}
                        observation=ObservationFilter.from_mapping(question['filters'])
                        candidates=await runtime._retrieve_candidates({'filters':filters},vector_text)
                        expanded=await runtime._retrieve_evidence(candidates,vector_text,EvidenceCount.TWO,observation=observation)
                        pairs=build_pairs(candidates,expanded,EvidenceCount.TWO)
                        ranked=[]
                        if pairs:
                            response=await client.post('/rerank',json={'query':question['query'],'texts':[pair.text for pair in pairs]})
                            response.raise_for_status();scores=response.json()['scores'];http_calls['rerank']+=1
                            ranked=rank_places(candidates,pairs,scores)
                        expected=question['target_chunk'];target=question['target_place']
                        relevant_indexed=any(chunk.chunk_id==expected for chunk in selections[target]) if expected else None
                        relevant_pairs=[pair for pair in pairs if candidates[pair.candidate_index]['place_id']==target and pair.evidence and pair.evidence['chunk_id']==expected]
                        final=next((row for row,score in ranked if row['place_id']==target),None)
                        result={'phase':phase,'id':question['id'],'target_indexed':relevant_indexed,
                            'candidate_count':len(candidates),'target_candidate_rank':next((index+1 for index,row in enumerate(candidates) if row['place_id']==target),None),
                            'target_reached_reranker':bool(relevant_pairs) if expected else None,
                            'target_final_rank':next((index+1 for index,(row,score) in enumerate(ranked) if row['place_id']==target),None),
                            'target_representative_correct':bool(final and final.get('evidence') and final['evidence']['chunk_id']==expected) if expected else None,
                            'rerank_pairs':len(pairs),'elapsed_ms':(time.perf_counter()-started)*1000,
                            'candidate_place_ids':[row['place_id'] for row in candidates],
                            'ranked_places':[{'place_id':row['place_id'],'score':score,'text':row['description'],'chunk_id':row.get('evidence',{}).get('chunk_id')} for row,score in ranked]}
                        all_results.append(result)
                        print(json.dumps({key:value for key,value in result.items() if key not in ('ranked_places','candidate_place_ids')},ensure_ascii=False),flush=True)
                finally:
                    await pool.close();await admin.execute(f'DROP SCHEMA {schema} CASCADE')
        finally:
            await admin.close()
        write_json(root/'embedding-cache.json',cache)
        report={'results':all_results,'health':health,'http_calls':http_calls,'embedding_cache_texts':len(cache),
            'production_database_writes':0,'search_executions':len(all_results),'sonar_calls_in_search':0,
            'evidence_count':2,'candidate_limit':30,'phases_are_separate':True,
            'note':'후속 단계 진단을 위한 검수 자료·감독 위치 정렬·40개 합성 방해 사례다. 모델 자동 성과나 운영 전체 검색 지표가 아니다.'}
        write_json(root/'search-summary.json',report)
    return root/'search-summary.json'


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--model-url',required=True)
    args=parser.parse_args()
    print(asyncio.run(run(args.root,args.model_url)))


if __name__=='__main__':
    main()
