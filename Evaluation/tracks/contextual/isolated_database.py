"""전용 폐기용 컨테이너에서만 PostgreSQL 검사 환경을 구성한다."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import sys
import unittest


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--full',action='store_true')
    args=parser.parse_args()
    host=os.environ['PGHOST']
    database=os.environ['PGDATABASE']
    if not host.startswith('tm-v7-eval-') or not database.startswith('contextual_v7_eval'):
        raise ValueError('운영 DB에는 연결하지 않습니다')
    os.environ['ENRICHMENT_TEST_DATABASE_URL']=f'postgresql://postgres@{host}:5432/{database}'
    os.environ['CONTEXTUAL_ISOLATED_DATABASE']='1'
    os.environ['LOCATION_REVIEW_DIR']='/tmp/contextual-v7-index-inputs'
    os.environ.pop('CONTEXTUAL_MODEL_TEST_URL',None)
    root=Path(__file__).resolve().parents[3]
    sys.path[:0]=[str(root/'embedding-server'),str(root/'embedding-server/tests')]
    suite=(unittest.defaultTestLoader.discover(str(root/'embedding-server/tests')) if args.full
           else unittest.defaultTestLoader.loadTestsFromName('test_contextual_supporting_postgres.SupportingPostgresTests'))
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    report={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
            'successful':result.wasSuccessful(),'scope':'full' if args.full else 'supporting-postgres',
            'production_database_writes':0,'api_calls':0,'model_search_executions':0,'log':stream.getvalue()}
    with args.output.open('x',encoding='utf-8') as target:
        json.dump(report,target,ensure_ascii=False,indent=2)
    if not result.wasSuccessful():
        print(stream.getvalue())
    print(json.dumps({key:value for key,value in report.items() if key!='log'},ensure_ascii=False))
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__=='__main__':
    main()
