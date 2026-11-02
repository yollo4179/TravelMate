"""보존한 실제 벡터로 후보 상한·활성 상한 손실을 별도 진단한다."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid
from unittest.mock import patch

import asyncpg
import httpx

from Evaluation.tracks.contextual.v7_search import ROOT,portable,distractors
from app.contextual.artifacts import load_record
from app.contextual.contracts import SearchChunk,SplitterVersion
from app.contextual.pipeline import select_active,index_embedding_inputs
from app.contextual.repository import activate_chunks
from app.contextual.observation_search import ObservationFilter
from app.contextual.ranking import EvidenceCount,build_pairs,rank_places
from app.contextual.review import reviewed_chunks
from app.enrichment.artifacts import write_json
from app.enrichment.repository import ensure_schema


async def run(root: Path,base_url: str) -> Path:
    if (root/'recall-audit-plan.json').exists():
        raise ValueError('기존 진단을 자동 재실행하지 않습니다')
    host=os.environ['PGHOST'];database=os.environ['PGDATABASE']
    if not host.startswith('tm-v7-eval-') or not database.startswith('contextual_v7_eval'):
        raise ValueError('폐기용 DB가 아닙니다')
    summary=json.loads((root/'sonar/generation-summary.json').read_text(encoding='utf-8'))
    cache=json.loads((root/'embedding-cache.json').read_text(encoding='utf-8'))
    places={};approved=[];supporting=None
    for result in summary['results']:
        path=portable(result['record'],root)
        bundle,_,record=load_record(path)
        places.update({place.place_id:place for place in bundle.places})
        approved.extend(reviewed_chunks(path,root/f'approval-{result["id"]}.json'))
        if result['id']=='CONTROL':
            row=next(row for row in record['excluded_chunks'] if row['relations'] and row['relations'][0]['importance']=='supporting')
            source=next(source for source in bundle.sources if source.source_id==row['source_id'])
            relation=json.loads(json.dumps(row['relations'][0]))
            quote=relation['evidence']['quote'];left=source.text.index(quote)
            relation['evidence'].update(start=left,end=left+len(quote))
            raw=json.loads(path.with_name('raw_response.json').read_text(encoding='utf-8'))
            supporting=SearchChunk(source,row['start'],row['end'],row['context_text'],row['place_refs'],
                {'provider':'diagnostic-only','model':raw['model'],'prompt_version':record['prompt_version'],
                 'response_id':raw['id'],'processing':'unique-exact-quote-alignment-diagnostic-v1'},row['entities'],[],
                SplitterVersion.SENTENCE,row['content_kind'],[relation])
    if supporting is None:
        raise ValueError('보조 관계 진단 누락')
    negatives,negative_chunks=distractors();places.update(negatives)
    chunks=approved+negative_chunks+[supporting]
    selections={identifier:select_active(identifier,chunks) for identifier in places}
    b_eligible=[chunk for chunk in chunks if 202 in chunk.index_place_ids]
    write_json(root/'recall-audit-plan.json',{'candidate_limit_diagnostic':100,'production_limit_unchanged':30,
        'before_b_eligible':len(b_eligible),'before_b_active':len(selections[202]),'target_in_b_active':supporting in selections[202],
        'diagnostic_b_active_ids':[supporting.chunk_id]+[chunk.chunk_id for chunk in selections[202]][:19],
        'uses_saved_embedding_cache':True,'new_sonar_calls':0,'production_database_writes':0})
    admin=await asyncpg.connect(host=host,user='postgres',database=database)
    schema='v7_audit_'+uuid.uuid4().hex
    await admin.execute(f'CREATE SCHEMA {schema}')
    pool=await asyncpg.create_pool(host=host,user='postgres',database=database,min_size=1,max_size=3,
        server_settings={'search_path':schema+',public'})
    try:
        await pool.execute((ROOT/'Docker/search-init/01-search-schema.sql').read_text(encoding='utf-8'))
        await ensure_schema(pool)
        for place in places.values():
            mapping=place.to_dict();columns=list(mapping)
            await pool.execute('INSERT INTO place_embeddings('+','.join(columns)+',source_version,latest_seen_version) VALUES('
                +','.join(f'${i+1}' for i in range(len(columns)))+',1,1)',*mapping.values())
        async with pool.acquire() as connection:
            async with connection.transaction():
                for identifier,selected in selections.items():
                    texts,primary=index_embedding_inputs(places[identifier],selected)
                    vectors=[cache[text] for text in texts]
                    await activate_chunks(connection,identifier,selected,vectors[:len(selected)])
                    await connection.execute('UPDATE place_embeddings SET embedding=$2::vector WHERE place_id=$1',identifier,'['+','.join(map(str,vectors[primary]))+']')
        with patch.dict(sys.modules,{'app.embedder':SimpleNamespace(embedder=None),'app.reranker':SimpleNamespace(reranker=None)}):
            module=importlib.import_module('app.kafka_runtime')
        runtime=object.__new__(module.KafkaRuntime);runtime.database_pool=pool
        results=[]
        async with httpx.AsyncClient(base_url=base_url,timeout=180,trust_env=False) as client:
            for identifier,query,condition in (
                ('remove-top30-only','B공원으로 걸어서 갈 수 있는 곳',{'destination_place_id':202,'relation_importance':['supporting']}),
                ('reserve-b-slot-only','A공원에서 관람 후 걸어서 갈 수 있는 공원',{'origin_place_id':101,'relation_importance':['supporting']}),
            ):
                if identifier=='reserve-b-slot-only':
                    selected=[supporting]+selections[202][:19]
                    async with pool.acquire() as connection:
                        async with connection.transaction():
                            await activate_chunks(connection,202,selected,[cache[chunk.embedding_text] for chunk in selected])
                vector='['+','.join(map(str,cache[query]))+']'
                observation=ObservationFilter.from_mapping(condition)
                with patch.object(module,'RETRIEVE_TOP_K',100 if identifier=='remove-top30-only' else 30):
                    candidates=await runtime._retrieve_candidates({'filters':{'observation':condition}},vector)
                expanded=await runtime._retrieve_evidence(candidates,vector,EvidenceCount.TWO,observation=observation)
                pairs=build_pairs(candidates,expanded,EvidenceCount.TWO)
                response=await client.post('/rerank',json={'query':query,'texts':[pair.text for pair in pairs]})
                response.raise_for_status();ranked=rank_places(candidates,pairs,response.json()['scores'])
                target=101 if identifier=='remove-top30-only' else 202
                result={'id':identifier,'candidate_count':len(candidates),
                    'target_candidate_rank':next((i+1 for i,row in enumerate(candidates) if row['place_id']==target),None),
                    'target_reached_reranker':any(candidates[pair.candidate_index]['place_id']==target and pair.evidence['chunk_id']==supporting.chunk_id for pair in pairs),
                    'target_final_rank':next((i+1 for i,(row,_) in enumerate(ranked) if row['place_id']==target),None),
                    'target_representative_is_supporting':any(row['place_id']==target and row['evidence']['chunk_id']==supporting.chunk_id for row,_ in ranked),
                    'candidate_place_ids':[row['place_id'] for row in candidates]}
                results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
        report={'results':results,'b_eligible':len(b_eligible),'b_active_before':len(selections[202]),
            'target_b_slot_in_original_selection':next((i+1 for i,chunk in enumerate(b_eligible) if chunk.chunk_id==supporting.chunk_id),None),
            'additional_embed_calls':0,'additional_rerank_calls':2,'additional_sonar_calls':0,'production_database_writes':0,
            'note':'감독 위치 정렬 후 합성 스트레스 자료의 상한만 바꾼 별도 진단이다. 운영 정책 개선이나 모델 자동 성공으로 집계하지 않는다.'}
        write_json(root/'recall-audit.json',report)
    finally:
        await pool.close();await admin.execute(f'DROP SCHEMA {schema} CASCADE');await admin.close()
    return root/'recall-audit.json'


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--model-url',required=True)
    args=parser.parse_args()
    print(asyncio.run(run(args.root,args.model_url)))


if __name__=='__main__':
    main()
