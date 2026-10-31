"""임베딩 컨테이너 안에서 비밀값 없이 검색 평가 환경을 읽기 전용 확인한다."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import urllib.request

import asyncpg


async def main() -> None:
    with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=10) as response:
        health = json.load(response)
    connection = await asyncpg.connect(os.environ['DATABASE_URL'])
    try:
        async with connection.transaction(readonly=True):
            counts = await connection.fetchrow("""SELECT count(*) AS places,
                count(*) FILTER(WHERE document_status='READY' AND source_version=latest_seen_version AND embedding IS NOT NULL) AS searchable,
                count(*) FILTER(WHERE place_id=394) AS target_rows FROM place_embeddings""")
            target = await connection.fetchrow('SELECT place_id,name,description,document_status FROM place_embeddings WHERE place_id=394')
            contextual_schema = await connection.fetchval("SELECT to_regclass('place_active_chunks') IS NOT NULL")
            active = await connection.fetchval('SELECT count(*) FROM place_active_chunks') if contextual_schema else None
    finally:
        await connection.close()
    print(json.dumps({'health': health, 'counts': dict(counts), 'target': dict(target) if target else None,
                      'contextual_schema_present': contextual_schema, 'active_chunks': active,
                      'runtime_sha256': hashlib.sha256(Path('/app/app/kafka_runtime.py').read_bytes()).hexdigest(),
                      'model_configuration': {name: os.environ.get(name) for name in (
                          'EMBEDDING_MODEL', 'EMBEDDING_REVISION', 'RERANK_BATCH_SIZE', 'RERANK_EXECUTION_STRATEGY')}},
                     ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
