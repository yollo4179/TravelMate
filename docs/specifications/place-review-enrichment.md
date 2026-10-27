# 기존 장소의 웹 근거 보강

기존 TourAPI 장소 ID·이름·좌표·지역·기본 설명을 유지한다. 신규 장소 발견은 하지 않는다.
Perplexity Agent API로 기존 장소의 추가 정보와 출처를 수집하고, FastAPI가 자기 검색 DB에
보강 스냅샷과 재색인 작업을 저장한다. Spring 원본은 수정하지 않는다.
리랭커 모델·실행 전략·Top-K는 변경하지 않았다. 임베딩도 현재 BGE-M3를 유지한다.

```text
기존 장소 → Agent API의 web_search·fetch_url → 전체 응답 아카이브
  → 스키마·장소 ID·인용/출처 검사 → 보강 스냅샷 저장 + 재색인 큐
  → 기존 임베딩 작업자가 기본 설명과 보강 설명을 함께 벡터화
  → 기존 검색·리랭킹 경로가 보강된 설명을 사용
```

## API 계약과 설정

공식 Python SDK의 /v1/responses, response_format.json_schema, output[]의 message/search_results/
fetch_url_results 형식을 기준으로 구현했다. /v1/agent나 최상위 search_results를 가정하지 않는다.

- https://github.com/perplexityai/perplexity-py/blob/main/api.md
- https://github.com/perplexityai/perplexity-py/blob/main/src/perplexity/types/response_create_params.py
- https://github.com/perplexityai/perplexity-py/blob/main/src/perplexity/types/output_item.py

저장소 루트 .env에 PERPLEXITY_API_KEY를 설정한다. PERPLEXITY_AGENT_PRESET과
PERPLEXITY_AGENT_MODEL 중 하나만 지정한다. 코드가 유료 모델을 자동 선택하지 않는다.
Sonar Pro를 시험하려면 콘솔에서 사용 가능한 프리셋명을 확인해 PERPLEXITY_AGENT_PRESET에
명시한다. CLI의 --preset 또는 --model로도 지정할 수 있다.
Pro/Max 웹 구독과 API 결제는 구분하고, 처음에는 소액 크레딧으로 실제 장소당 비용을 측정한다.
최신 가격은 https://docs.perplexity.ai/docs/getting-started/pricing 에서 확인한다.

Docker/stack-up.sh는 키와 선택값을 보호된 runtime.env로 전달한다. 키를 요청 아카이브나
로그에 넣지 않는다. .env에서 키/프리셋을 지우면 이전 전달값도 제거한다.

## 실행

새 코드와 의존성을 반영하도록 기존 스택을 다시 빌드한다. 기존 데이터 볼륨은 유지한다.
검색 DB 스키마는 최초 초기화 및 FastAPI 시작 시 멱등적으로 추가한다.

```bash
bash Docker/stack-up.sh
bash Docker/stack-wait.sh
```

수집 범위는 --place-id(반복 가능) 또는 --all-existing으로 직접 지정한다.
아래 ID 394는 평가 스냅샷의 청담도로공원 예시이며 로컬 DB에서 같은 장소인지 확인한다.
--execute가 없으면 키 없이도 요청 미리보기만 저장하며 외부 API를 호출하지 않는다.

```bash
docker exec travelmate-embedding python -m app.enrichment.cli collect --from-search-db --place-id 394 --preset sonar-pro --output /enrichment-data
```

실제 과금 호출은 같은 명령에 --execute를 붙인다. --all-existing을 자동으로 실행하지 않는다.
동일 기본정보·프롬프트·프리셋의 성공 기록이 있으면 재사용한다. 새 수집은 --refresh로 명시한다.
429/연결 오류를 무조건 재시도해 중복 과금하지 않으며 실패 유형을 기록한다.
401·403·429에서는 배치의 나머지 장소를 호출하지 않고 중단한다.

```bash
docker exec travelmate-embedding python -m app.enrichment.cli collect --from-search-db --place-id 394 --preset sonar-pro --output /enrichment-data --execute
```

각 출력의 record 경로를 사용해 검색 반영을 별도로 실행한다. 아래 경로는 형식 예시다.

```bash
docker exec travelmate-embedding python -m app.enrichment.cli apply --record /enrichment-data/requests/REQUEST_HASH/SNAPSHOT_ID/record.json
```

REINDEX_QUEUED는 벡터 갱신 완료가 아니라 재색인 작업 등록을 뜻한다.
기존 place_index_jobs가 SUCCEEDED가 된 뒤 검색 결과에 반영된다. 같은 스냅샷의 재적용은
ALREADY_APPLIED이며 재색인 작업을 중복 생성하지 않는다.
원본이 바뀌었거나 삭제·인덱싱 중이면 이전 수집 결과의 적용을 거부한다.

호스트에서도 embedding-server 디렉터리에서 python -m app.enrichment.cli를 사용할 수 있다.
--env-file ../.env는 서브명령 앞에 둔다. collect --input으로 기존 장소 JSON 배열/JSONL을
읽을 수 있지만 apply는 FastAPI 검색 DB의 실제 기존 행과 기본정보 일치를 다시 확인한다.
DATABASE_URL은 Spring DB가 아니라 FastAPI 검색 DB여야 한다.

## 보존과 검색 반영 기준

- 요청·raw_response.json·record.json을 보존하며 새 수집은 새 UUID 경로에 쓴다.
- raw_response에는 공급자가 반환한 자료 전체를 보존한다. 웹 전체·모든 리뷰 본문을 수집했다는 뜻은 아니다.
- 검색 결과/URL fetch의 실제 snippet에서 인용문을 공백 정규화 후 찾을 수 있는지 검사한다.
  생성된 JSON 안에 인용문을 쓰는 것만으로는 이 검사를 통과하지 못한다.
- PROVIDER_EXCERPT_MATCHED는 공급자가 반환한 조각과의 일치다. 별도 원문 접속·독립 사실 검증·사람 검수 완료를 뜻하지 않는다.
- entity_match는 모델의 장소 일치 판단이며 독립적인 지리 검증은 아니다. ID 변경이나 불명확한 대상은 검색에 반영하지 않는다.
- 상충한 aspect와 미확인 인용은 기록에 남기되 확정된 검색 특성으로 넣지 않는다.
- 검색 문서에 들어가는 후기는 조건·인용·URL과 '웹 자료의 관찰·후기'라는 표시를 유지한다.
- place_embeddings.description 등 기본정보를 덮어쓰지 않고 search_description에 별도로 저장한다.
- source_fingerprint가 달라지면 기존 보강을 새 기본정보에 조용히 재사용하지 않는다.
- 재색인 중 더 최신 보강이 적용되면 오래된 작업이 그 결과를 덮어쓰지 못하도록 SQL에서 확인한다.

/enrichment-data는 전용 Docker 볼륨이다. 원문·출처 아카이브는 Git에 자동 포함하지 않는다.
조회 응답의 description에는 보강 문맥을 포함하고, DB 기본 description은 그대로 유지한다.
Kafka 완료 항목의 enrichment_snapshot_id로 사용한 보강 버전을 추적하며 Spring은 원본 완료 메시지를 보존한다.
새로운 Spring DTO나 프런트엔드 출처 카드 UI를 구현한 것은 아니다.

## 검증 범위와 남은 작업

테스트는 모의 Agent 응답과 격리된 PostgreSQL에서 인용 검사·캐시·멱등성·원본 변경 거부·재색인을 확인한다.
실제 Perplexity 인증·요금·응답 품질은 API 키를 설정해 사용자가 선택한 장소로 실행해야 확인된다.
현재 Agent 규격은 공식 SDK를 기준으로 했으며 실제 계정의 모델/프리셋 지원도 확인해야 한다.
검색 문서가 길어지므로 토큰 길이·리랭킹 p50/p95와 관련도 지표를 다시 측정해야 한다.
이 변경으로 평가용 동결 코퍼스·정답 판정·사람 검수 기록을 수정하지 않았다.

```bash
python -m unittest discover -s embedding-server/tests -v
```

DB 통합 테스트에는 ENRICHMENT_TEST_DATABASE_URL로 명시한 별도 테스트 DB가 필요하다.
각 테스트는 고유 스키마를 만들고 자기 스키마만 제거한다. 운영 DB를 테스트 대상으로 쓰지 않는다.
