# Kafka·CQRS 추천 API·이벤트·DB 명세

[추천 구조도](../architecture/fastapi-place-recommendation.md) · [문서 목록](../README.md) · [투어 가이드 명세](personal-tour-guide.md)

갱신일: 2026-10-25, 한국 시간. 코드 확인 기준: `f9f09db`, 이전 문서: `6e18c16`. **Kafka 사용과 검색 테이블에 본문·필터용 복사본 저장은 사용자 확정 사항입니다. 아래 API·스키마·작업 상태는 구현 계약 제안이며 아직 실행 코드에 적용하지 않았습니다.**

## 1. 책임과 테이블

| 영역 | 소유자 | 역할 |
|---|---|---|
| `places` | Spring | 관광지 원본과 증가하는 content_version |
| `place_change_outbox` | Spring | 원본 변경과 원자적으로 기록한 전송할 이벤트 |
| `place_embeddings` | FastAPI | 검색용 벡터·본문·필터 복사본·버전·삭제 표식 |
| `place_index_jobs` | FastAPI | 이벤트 영속 접수·중복 제거·임베딩 작업 상태 |
| 사용자·계획·기억 | Spring | 인증·Context·변경안·저장·롤백 |

같은 PostgreSQL을 사용하되 수정 계정을 분리합니다. FastAPI는 원본 `places`를 직접 조회·JOIN·수정하지 않습니다. Spring은 검색 인덱스를 직접 UPDATE하지 않습니다. 운영 마이그레이션 계정은 별도로 관리합니다.

검색용 복사본의 원본은 항상 Spring 이벤트입니다. 관광지 내용을 모델이 생성해 덮어쓰는 권한을 FastAPI에 부여하지 않습니다. 온라인 검색, Kafka 접수, 인덱싱은 모듈과 실행 책임을 분리합니다.

## 2. Kafka 이벤트와 전달

### 2.1 토픽 계약 제안

| 항목 | 계약 |
|---|---|
| 토픽 | `travelmate.place-changes.v1` |
| 메시지 key | place_id의 문자열 |
| 이벤트 종류 | `PLACE_UPSERTED`, `PLACE_DELETED` |
| 소비자 그룹 | `travelmate-place-indexer-v1` |
| payload 버전 | schema_version으로 관리 |
| 전송 의미 | at-least-once. 재발행·재접수 가능 |
| 발행 확인 | Kafka 발행 확인 후 Outbox 전달 상태 갱신. producer idempotence·acks 설정으로 전송을 보강 |
| offset commit | 자동 commit을 끄고 DB 영속 접수 후 해당 파티션의 연속 접수 구간까지 commit |

로컬 브로커·토픽·Kafka UI 실행 구성은 [Docker 안내](../../Docker/KAFKA_README.md)를 따릅니다. Kafka 클라이언트 라이브러리·운영 브로커 버전·파티션·복제·retention 수치는 미정입니다. producer idempotence만으로 DB 반영까지 exactly-once가 되는 것은 아닙니다. 토픽 key가 같아도 여러 relay의 발행 순서와 임베딩 완료 순서를 원본 버전 순서라고 가정하지 않습니다.

### 2.2 등록·수정 이벤트 예시

아래 ID·내용·시간은 계약 설명용 예시이며 실제 수집·측정 결과가 아닙니다. payload는 해당 원본 버전의 완전한 검색 스냅샷입니다.

```json
{
  "schema_version": 1,
  "event_id": "ed787306-7859-48ba-87c8-7b7f79d3ba62",
  "event_type": "PLACE_UPSERTED",
  "place_id": 378,
  "source_version": 6,
  "occurred_at": "2026-10-25T00:00:00+09:00",
  "source": {
    "name": "창경궁",
    "description": "검색 인덱스 계약 설명용 본문입니다.",
    "region": "서울",
    "city": "종로",
    "category": "관광지",
    "source_category": "고궁",
    "latitude": 37.5794,
    "longitude": 126.9910
  }
}
```

Spring은 원본 저장과 이벤트 스냅샷 작성을 같은 트랜잭션으로 처리합니다. relay가 발행할 때 최신 원본을 다시 읽어 과거 이벤트의 version과 새 본문을 섞지 않습니다. `source_version`은 장소별로 단조 증가하며 현재 `places`에 추가할 필드입니다. 동시 수정은 row lock 또는 optimistic version 검증으로 보호합니다.

이벤트 payload 해시를 기록해 같은 event_id에 다른 내용이 오면 충돌로 처리합니다. 이미지·홈페이지 등 최종 상세는 Spring이 조회합니다. 검색 복사본에는 후보 검색·리랭킹·필터에 필요한 필드를 담습니다.

### 2.3 삭제 이벤트 예시

```json
{
  "schema_version": 1,
  "event_id": "f460ab5a-2852-4830-9930-e7640021a777",
  "event_type": "PLACE_DELETED",
  "place_id": 378,
  "source_version": 7,
  "occurred_at": "2026-10-25T00:10:00+09:00",
  "source": null
}
```

DELETE 접수 시 검색 행에 삭제 버전을 남기고 벡터·복사본을 검색 대상에서 제외합니다. 단순 DELETE로 버전 표식까지 지우면 늦은 UPSERT가 행을 되살릴 수 있습니다. 원본의 soft delete·hard delete 정책과 삭제 표식 보관 기간은 별도 확정합니다. hard delete 이후에도 버전 표식을 유지할 수 있도록 검색 테이블에 원본 생존을 요구하는 물리 FK를 무조건 추가하지 않습니다.

### 2.4 Outbox와 작업 접수 규칙

1. Spring은 `places` 변경과 Outbox 삽입을 함께 commit합니다. 모델 호출·Kafka 발행을 이 DB 트랜잭션 안에서 기다리지 않습니다.
2. relay는 미전달 이벤트를 확보하고 Kafka 발행 확인 후 전달 상태를 갱신합니다. 확인이 불확실하면 같은 event_id로 재전송합니다.
3. FastAPI 소비자는 event_id·스키마·버전을 검증하고 작업을 영속 저장합니다. 같은 트랜잭션에서 장소별 최신 수신 버전을 올립니다. 최신 이벤트의 DELETE만 적용하고, 과거 버전은 SUPERSEDED로 구분합니다. 같은 장소·원본 버전에 서로 다른 payload가 오면 충돌로 처리합니다.
4. 접수 commit 이후 offset을 commit합니다. 장애 후 재수신되면 같은 event_id의 작업을 재사용합니다.
5. 임베딩 작업자는 영속 접수 기록에서 작업을 확보합니다. 짧은 확보 트랜잭션 후 DB 연결을 반환하고 모델을 실행합니다.
6. 완료 반영 시 장소별 버전 행을 잠그고 현재 작업이 최신 수신 버전이며 대상 인덱스 설정 세대와 일치하는지 확인합니다. 일치할 때만 본문·필터·벡터·source_version을 원자적으로 반영하고 작업을 성공으로 기록합니다.
7. v6 접수 후 늦게 끝난 v5는 `SUPERSEDED`로 기록하고 인덱스를 덮어쓰지 않습니다. 삭제 역시 같은 장소 버전 검사와 잠금 규칙을 따릅니다.

메시지 영속 접수와 검색 반영 완료는 다른 상태입니다. 접수 후 처리 실패는 작업 상태·재시도로 관리합니다. 재시도 횟수·간격·격리 토픽/DLQ 정책은 미정이며, 영구 오류를 무한 반복하거나 정상 반영으로 기록하지 않습니다. 불량 이벤트는 추적 가능한 격리 기록을 남기고 처리 정책에 맞게 offset 진행을 결정합니다.

## 3. 논리 데이터 모델

아래는 마이그레이션 전 논리 계약입니다. 기존 컬럼·테이블이 이미 존재한다는 뜻은 아닙니다.

| 테이블 | 주요 필드 | 제약·소유권 |
|---|---|---|
| `places` 확장 | 기존 원본 필드, content_version | Spring이 버전 증가와 원본 변경·이벤트 기록을 함께 수행 |
| `place_change_outbox` | event_id, place_id, source_version, event_type, schema_version, payload, payload_hash, publication_status, published_at | event_id 유일. 전달 완료와 인덱싱 완료를 혼동하지 않음 |
| `place_embeddings` | place_id, source_version, latest_seen_version, name, description, region, city, category, source_category, latitude, longitude, embedding, embedding_input_hash, embedding_model_id, embedding_model_revision, index_config_version, desired_index_config_version, document_status, indexed_at | FastAPI만 수정. 벡터는 현행 1024차원. 적용된 복사본 전체는 source_version에 대응 |
| `place_index_jobs` | job_id, origin_type, event_id nullable, request_id, place_id, source_version, payload, payload_hash, index_config_version, status, attempt_count, next_attempt_at, lease_owner, lease_until, last_error_code | 이벤트 접수의 event_id 유일. 초기 이관·재색인은 새 작업 ID와 요청·원본 버전·설정 세대로 중복 제어 |

`latest_seen_version`은 소비자가 확인한 최신 원본 버전, `source_version`은 현재 반영된 문서·벡터의 버전입니다. 새 이벤트 수신만으로 적용된 본문이나 source_version을 먼저 바꾸지 않습니다. 두 버전이 다르면 진행 중인 인덱스 지연입니다. `desired_index_config_version`은 반영 대상 설정 세대이며, 과거 설정의 늦은 작업도 최신 설정을 덮어쓰지 못하게 합니다.

`document_status`는 `READY` 또는 `DELETED`를 구분합니다. 아직 벡터가 없는 초기 행은 검색에서 제외합니다. 작업 상태 제안은 `PENDING`, `RUNNING`, `RETRY_PENDING`, `SUCCEEDED`, `SUPERSEDED`, `FAILED`입니다. 구현 시 종류와 상태를 Enum으로 관리합니다.

`embedding_input_hash`는 실제 임베딩에 사용한 문자열·전처리와 대응시킵니다. 현행 배치는 `name + ". " + description`을 사용하므로 첫 이전에서 이를 보존하고 null·정규화 처리도 동일하게 검증합니다. 리랭킹 입력은 현행 description입니다.

모델·전처리가 같은 상태에서 입력 해시도 같다면 기존 벡터 재사용을 검토할 수 있습니다. 원본 버전이 같아도 모델 revision이 바뀌는 재색인은 새 `index_config_version`으로 관리합니다. 모델 변경과 원본 수정의 버전 검사를 하나로 혼동하지 않습니다.

## 4. 온라인 추천 API

`POST /internal/v1/place-search`

Spring이 내부 인증과 `traceparent`를 전달합니다. FastAPI는 자신의 검색 테이블만 조회하고 쿼리 임베딩·리랭킹을 내부 함수로 호출합니다. 원본 등록 이벤트의 Kafka 경로와 온라인 검색의 HTTP 경로를 구분합니다.

### 4.1 요청 예시

```json
{
  "request_id": "search-example-001",
  "query": "왕실 가족이 생활했던 공간",
  "filters": {
    "region": "서울",
    "city": "종로",
    "category": null,
    "area": null,
    "exclude_place_ids": [378]
  },
  "ranking_mode": "RERANKED",
  "limit": 10
}
```

내부 `ranking_mode`는 명시 필수이며 현행 `SEMANTIC_ONLY`, `RERANKED`를 사용합니다. 최종 limit는 기존 공개 검색의 1~20 검증을 유지합니다. 첫 이전의 후보 수는 현행 최대 30을 보존하되 최적값으로 확정한 수치로 해석하지 않습니다.

`area`는 null 또는 아래 CIRCLE 구조입니다. 현재 Context의 500~10000m 반경 검증과 lat/lon 의미를 유지합니다. 현재 미지원인 REGION 검색을 이전만으로 지원한다고 표시하지 않습니다.

```json
{
  "type": "CIRCLE",
  "center": {"lat": 37.5794, "lon": 126.9910},
  "radius_meters": 1000
}
```

개인 기억·대화 원문 전체 대신 Spring이 확정한 쿼리와 조건을 전달합니다. 취향 선호와 지역·반경·제외 같은 필수 조건을 구분합니다. 후보·원문·필터 모두 `place_embeddings`의 같은 적용 버전에서 읽습니다.

### 4.2 응답 예시

다음은 빈 후보 결과의 계약 예시입니다. 실제 시간이나 모델 점수를 만들어 넣지 않았습니다.

```json
{
  "request_id": "search-example-001",
  "ranking_mode_requested": "RERANKED",
  "ranking_mode_applied": "RERANKED",
  "rerank_status": "EMPTY",
  "fallback_reason": null,
  "candidate_count": 0,
  "returned_count": 0,
  "applied_filters": {
    "region": "서울",
    "city": "종로",
    "category": null,
    "area": null,
    "exclude_place_ids": [378]
  },
  "items": []
}
```

후보가 있는 items는 최종 순서대로 다음 필드를 포함합니다.

| 필드 | 의미 |
|---|---|
| `place_id`, `rank` | 기존 places.id와 FastAPI가 정한 순위 |
| `source_version`, `latest_seen_version` | 검색 문서의 적용 버전과 최신 접수 버전 |
| `index_config_version` | 모델·전처리 설정 세대 |
| `semantic_score` | 현행 1 - cosine_distance |
| `rerank_score` | 현행 CrossEncoder 원점수. SEMANTIC_ONLY에서는 null |

FastAPI 응답의 장소 상세를 앱의 최신 원본으로 채택하지 않습니다. Spring이 IDs를 모아 원본을 한 번에 조회하고 기존 `PlaceSearchResponseDto`로 매핑합니다. 임베딩·리랭킹 점수는 인덱스의 source_version에 대한 점수라는 점을 유지합니다.

`rerank_status`는 `APPLIED`, `SKIPPED`, `EMPTY`를 구분합니다. fallback을 허용한 요청은 실제 적용 모드·이유를 명시합니다. 허용 정책·기본 모드·시간 예산은 미정이며, 대체 결과를 RERANKED 성공으로 집계하지 않습니다.

### 4.3 후보 조회와 최신성 확인

1. FastAPI는 현행 BGE-M3 쿼리 벡터의 차원·유한 값·정규화 방식과 인덱스 모델 세대를 검증합니다.
2. `document_status=READY`, embedding 존재, 사용 중인 인덱스 설정 세대를 조건으로 조회합니다. DELETE 표식 행은 제외합니다.
3. region·city·category·유효 좌표·반경·제외 ID를 후보 LIMIT 전에 적용합니다. 지역은 저장값 동등 비교, 반경은 기존 Haversine 직선거리식입니다.
4. 현행 최소 유사도 0.0과 cosine 거리 순위를 보존하고 같은 후보를 요청 모드로 정렬합니다. 본문과 벡터는 같은 source_version이어야 합니다.
5. DB 연결을 반환한 뒤 리랭킹합니다. 모델 점수 개수·유한 값·ID 중복을 검증하고 limit를 적용합니다.
6. Spring은 최신 원본을 일괄 조회해 ID별 map을 만들고 FastAPI 순서대로 결과를 복원합니다. 후보별 추가 HTTP·DB 호출을 반복하지 않습니다.
7. 원본 존재·content_version·필수 조건을 검증합니다. 삭제·버전 불일치·조건 변경은 `INDEX_LAG` 또는 명시적 무효 후보로 구분합니다.

오래된 인덱스 순위와 새 원문을 섞어 최신 내용으로 채점된 추천처럼 표시하지 않습니다. 버전 불일치 시 부분 반환·추가 후보 조회·재시도 등 사용자 응답 정책은 별도 확정합니다. 필수 조건을 자동 완화하지 않습니다. 계획 적용 시에는 다시 소유권·최신 계획 버전·장소 조건을 확인합니다.

### 4.4 오류와 상태

| 구분 | 의미 |
|---|---|
| 200, items 빈 목록 | 현재 조회 가능한 인덱스에서 조건 내 후보 없음. DB 실패와 구분 |
| 422 | 입력·벡터 차원·지원하지 않는 범위 오류 |
| 503 | 검색 DB·필수 모델·실행기 사용 불가 |
| 504 | 요청 처리 기한 초과 |
| Spring의 INDEX_LAG 상태 | 검색 후보와 원본 버전 불일치. HTTP·사용자 응답 정책은 미정 |

Kafka 장애와 인덱스 지연은 검색 DB 장애와 별도로 관측합니다. 기존 복사본이 조회된다고 최신 원본까지 반영됐다고 표시하지 않습니다. 원본 저장 API도 저장 성공을 즉시 검색 가능 상태와 동일하게 표시하지 않습니다.

## 5. DB·모델·Kafka 자원 관리

- Spring 계정은 원본·업무 테이블·Outbox를 수정하고 검색 인덱스는 수정하지 않습니다. FastAPI 조회 계정은 검색 인덱스 SELECT, 인덱싱 계정은 인덱스·접수/작업 상태의 필요한 읽기·쓰기를 담당하도록 분리합니다.
- FastAPI에 원본 places·사용자·계획 테이블의 접근 권한을 부여하지 않습니다. PostgreSQL 스키마·테이블 권한으로 경계를 강제합니다.
- 드라이버 제안은 SQLAlchemy 비동기 엔진·asyncpg·pgvector 어댑터입니다. 기존 PostgreSQL 내부 주소를 사용하고 DB 풀은 lifespan에서 관리합니다.
- 모델·Kafka 클라이언트·DB 풀 수명을 관리합니다. 모델을 요청마다 로드하지 않고 동기 추론으로 HTTP 이벤트 루프나 Kafka poll을 막지 않도록 실행기를 둡니다.
- GPU 온라인 리랭킹과 관광지 배치 임베딩의 자원 경쟁을 제한합니다. 동시 실행 수·배치·토큰·큐 한도는 측정 후 확정합니다.
- 작업자의 lease 만료는 GPU 작업 종료를 보장하지 않습니다. 재확보·중복 실행이 발생해도 버전·원자적 반영으로 결과를 보호하고 실제 실행 슬롯을 추적합니다.
- Kafka 브로커와 소비자 운영, 토픽 생성·권한·보관·실패 복구는 구현 범위입니다. 로컬 구성과 운영 복제·장애 보장 수준을 구분합니다.
- DB 비밀번호·Kafka 인증·Authorization은 설정 비밀값으로 전달하고 로그에 노출하지 않습니다. FastAPI 시작 시 원본 DDL이나 자동 테이블 재생성을 실행하지 않습니다.

## 6. 관측과 검증

온라인 trace는 Spring → FastAPI → 쿼리 임베딩·인덱스 조회·리랭킹 → Spring 상세 조회·버전 검증을 연결합니다. Kafka 인덱싱은 이벤트 ID·placeId·source_version으로 생산·접수·작업·반영을 추적합니다. 긴 비동기 처리는 별도 trace와 link로 연결할 수 있으며 span ID와 trace ID를 구분합니다.

| 관측 항목 | 구분할 내용 |
|---|---|
| 원본 commit → Kafka 발행 → 영속 접수 → 검색 반영 | 단계별 지연. producer 전송 지연과 모델 추론 구분 |
| Outbox 미전달·소비자 lag·접수 작업 backlog | Kafka offset commit 후 DB 작업 backlog도 별도 확인 |
| 실패·재시도·중복·SUPERSEDED·삭제 표식 | 정상 처리 수와 혼동하지 않음 |
| source_version·latest_seen_version·원본 content_version | 복사본 내부 지연과 Spring 원본 대비 지연 구분 |
| 모델·revision·dtype·장치·토큰·배치·큐 대기 | 추론 재현 조건 |
| 검색 전체·리랭커 추론·Spring 상세 조회 | 서로 다른 지연 구간 |

사용자 목표는 리랭커 추론 약 0.5초 이하입니다. 전체 검색 시간 목표·평균/백분위·입력 조건은 미정입니다. Kafka 적용이 이 추론 목표 달성을 의미하지 않습니다.

검증에는 원본·Outbox 원자성, 발행 확인 직후 장애, 접수 직후 offset commit 전 장애, 중복 이벤트, v6 완료 후 v5 완료, 삭제 후 과거 UPSERT, 인덱스 실패·재시작, 같은 버전 벡터·본문·필터 반영, Spring 상세 조회 순서 복원과 버전 불일치를 포함합니다. 이는 후속 구현의 수용 항목이며 이번 문서 작업에서 실행한 테스트 결과가 아닙니다.

검색 품질은 합의한 문항·검수표·@5/@10과 Precision·Recall·F1·MAP·NDCG·MRR를 유지해 비교합니다. 같은 원본·인덱스 세대와 동기화 상태로 비교하고 미반영·실패 문항을 숨기지 않습니다. 새 평가 범위나 허용 품질 하락률은 정하지 않습니다.

## 7. 초기 이관과 남은 결정

현재 `places.embedding vector(1024)`과 Spring의 `ReembeddingService`가 벡터를 관리합니다. 전환 후에는 FastAPI가 임베딩 생성과 검색 테이블 반영을 소유합니다. 기존 관광지 ID와 원본은 유지합니다.

- 원본 content_version과 Outbox 변경 경로를 먼저 준비합니다. 기존 직접 SQL·수집 배치도 이벤트 누락 여부를 확인합니다.
- 검증된 기존 벡터는 초기 이관에 재사용할 수 있습니다. 모델·전처리·원문 대응이 확인되지 않는 행은 재색인합니다.
- 초기 스냅샷과 이후 이벤트를 버전으로 병합하고 최신 이벤트를 오래된 초기 복사가 덮어쓰지 않게 합니다.
- 같은 데이터 버전으로 기존 경로와 새 경로의 모드별 후보·점수·필터를 비교하고 Spring 상세 조회와 순서 복원을 확인합니다.
- 전환 검증 전에는 기존 컬럼·볼륨을 삭제하지 않습니다. 전환 후 Spring이 검색 인덱스 벡터를 다시 덮어쓰는 경로를 남기지 않습니다.

운영 GPU·모델 정밀도·토큰·배치·후보 수, Kafka 운영 수치·재시도/DLQ, 원본 삭제·삭제 표식 보관, 인덱스 최신성 사용자 응답 정책, 온라인 기본 모드·fallback 예산은 확인 후 확정합니다. 이름·별칭 검색·하이브리드·RRF는 확장 비교안이며 이번 선택만으로 기본 알고리즘이 되지 않습니다.
