# 별도 DB·Kafka 추천 요청/완료 이벤트 명세

[추천 구조도](../architecture/fastapi-place-recommendation.md) · [문서 목록](../README.md) · [투어 가이드 명세](personal-tour-guide.md)

갱신일: 2026-10-25, 한국 시간. 코드 확인 기준: `f9f09db`, 이전 문서: `7921ecb`. **별도 FastAPI DB와 Kafka 추천 요청·완료 전달, 완료 이벤트에 추천 장소 상세까지 포함하는 것은 사용자 확정 사항입니다. 원시 임베딩 벡터를 완료 결과로 보내는 계약이 아닙니다. 아래 내용은 로컬 Codex 구현과 맞출 문서 계약이며, 이번 갱신으로 실행 코드를 변경하지 않습니다.**

## 1. DB 경계와 데이터 소유권

| 위치 | 저장 내용 | 소유자 |
|---|---|---|
| Spring DB | places 원본·content_version, 사용자·계획·기억 | Spring |
| Spring DB | 원본 변경 Outbox, 추천 요청·요청 Outbox·수신 결과 | Spring |
| 별도 FastAPI DB | place_embeddings의 벡터·본문·필터·응답용 상세 복사본 | FastAPI |
| 별도 FastAPI DB | 인덱싱·추천 작업, 추천 결과와 결과 Outbox | FastAPI |

두 DB는 별도 PostgreSQL 서비스·접속 정보·계정·마이그레이션·백업 경계를 갖습니다. 각 서비스는 자신의 DB에만 접속하며 cross-DB JOIN·공유 트랜잭션·물리 FK를 사용하지 않습니다. 두 DB의 원본 ID·버전은 논리 참조입니다.

본문·이미지·좌표 등 복사본의 원본은 Spring 변경 이벤트입니다. FastAPI가 관광지 설명을 생성해 원본처럼 덮어쓰지 않습니다. 온라인 추천 결과는 해당 복사본의 일관된 스냅샷이며 Spring은 상세 보충을 위해 원본을 재조회하지 않습니다.

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
    "longitude": 126.9910,
    "tour_content_id": "example-content-id",
    "image_url": null,
    "homepage_url": null
  }
}
```

Spring은 원본 저장과 이벤트 스냅샷 작성을 같은 트랜잭션으로 처리합니다. relay가 발행할 때 최신 원본을 다시 읽어 과거 이벤트의 version과 새 본문을 섞지 않습니다. `source_version`은 장소별로 단조 증가하며 현재 `places`에 추가할 필드입니다. 동시 수정은 row lock 또는 optimistic version 검증으로 보호합니다.

이벤트 payload 해시를 기록해 같은 event_id에 다른 내용이 오면 충돌로 처리합니다. 이미지·홈페이지·출처 ID 등 최종 응답에 필요한 상세도 이벤트에 포함합니다. FastAPI 검색 복사본에 저장해 완료 payload를 구성하며, Spring이 다시 상세를 조회하는 경로를 만들지 않습니다.

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
6. 완료 반영 시 장소별 버전 행을 잠그고 현재 작업이 최신 수신 버전이며 대상 인덱스 설정 세대와 일치하는지 확인합니다. 일치할 때만 본문·필터·이미지 등 응답 상세·벡터·source_version을 원자적으로 반영하고 작업을 성공으로 기록합니다.
7. v6 접수 후 늦게 끝난 v5는 `SUPERSEDED`로 기록하고 인덱스를 덮어쓰지 않습니다. 삭제 역시 같은 장소 버전 검사와 잠금 규칙을 따릅니다.

메시지 영속 접수와 검색 반영 완료는 다른 상태입니다. 접수 후 처리 실패는 작업 상태·재시도로 관리합니다. 재시도 횟수·간격·격리 토픽/DLQ 정책은 미정이며, 영구 오류를 무한 반복하거나 정상 반영으로 기록하지 않습니다. 불량 이벤트는 추적 가능한 격리 기록을 남기고 처리 정책에 맞게 offset 진행을 결정합니다.

## 3. 논리 데이터 모델

아래는 마이그레이션 전 논리 계약입니다. places와 변경 Outbox는 Spring DB, 검색 인덱스와 작업 기록은 FastAPI DB에 둡니다. 기존 컬럼·테이블이 이미 존재한다는 뜻은 아닙니다.

| 테이블 | 주요 필드 | 제약·소유권 |
|---|---|---|
| `places` 확장 | 기존 원본 필드, content_version | Spring이 버전 증가와 원본 변경·이벤트 기록을 함께 수행 |
| `place_change_outbox` | event_id, place_id, source_version, event_type, schema_version, payload, payload_hash, publication_status, published_at | event_id 유일. 전달 완료와 인덱싱 완료를 혼동하지 않음 |
| `place_embeddings` | place_id, source_version, latest_seen_version, name, description, region, city, category, source_category, latitude, longitude, tour_content_id, image_url, homepage_url, embedding, embedding_input_hash, embedding_model_id, embedding_model_revision, index_config_version, desired_index_config_version, document_status, indexed_at | FastAPI만 수정. 벡터는 현행 1024차원. 적용된 복사본 전체는 source_version에 대응 |
| `place_index_jobs` | job_id, origin_type, event_id nullable, request_id, place_id, source_version, payload, payload_hash, index_config_version, status, attempt_count, next_attempt_at, lease_owner, lease_until, last_error_code | 이벤트 접수의 event_id 유일. 초기 이관·재색인은 새 작업 ID와 요청·원본 버전·설정 세대로 중복 제어 |

`latest_seen_version`은 소비자가 확인한 최신 원본 버전, `source_version`은 현재 반영된 문서·벡터의 버전입니다. 새 이벤트 수신만으로 적용된 본문이나 source_version을 먼저 바꾸지 않습니다. 두 버전이 다르면 진행 중인 인덱스 지연입니다. `desired_index_config_version`은 반영 대상 설정 세대이며, 과거 설정의 늦은 작업도 최신 설정을 덮어쓰지 못하게 합니다.

`document_status`는 `READY` 또는 `DELETED`를 구분합니다. 아직 벡터가 없는 초기 행은 검색에서 제외합니다. 작업 상태 제안은 `PENDING`, `RUNNING`, `RETRY_PENDING`, `SUCCEEDED`, `SUPERSEDED`, `FAILED`입니다. 구현 시 종류와 상태를 Enum으로 관리합니다.

`embedding_input_hash`는 실제 임베딩에 사용한 문자열·전처리와 대응시킵니다. 현행 배치는 `name + ". " + description`을 사용하므로 첫 이전에서 이를 보존하고 null·정규화 처리도 동일하게 검증합니다. 리랭킹 입력은 현행 description입니다.

모델·전처리가 같은 상태에서 입력 해시도 같다면 기존 벡터 재사용을 검토할 수 있습니다. 원본 버전이 같아도 모델 revision이 바뀌는 재색인은 새 `index_config_version`으로 관리합니다. 모델 변경과 원본 수정의 버전 검사를 하나로 혼동하지 않습니다.

## 4. Kafka 추천 요청·완료 계약

추천은 Spring → Kafka → FastAPI → Kafka → Spring 흐름입니다. 이전 `POST /internal/v1/place-search` 동기 HTTP 제안을 이 흐름으로 대체합니다. 앱의 접수·대기·결과 수신 API는 별도 확정하며 현재 동기 GET API와 자동 호환된다고 표시하지 않습니다.

### 4.1 토픽과 상관관계

| 토픽 제안 | producer → consumer | key와 이벤트 |
|---|---|---|
| `travelmate.place-changes.v1` | Spring → FastAPI | key=place_id, 기존 원본 변경·삭제 |
| `travelmate.recommendation-requests.v1` | Spring → FastAPI | key=request_id, `RECOMMENDATION_REQUESTED` |
| `travelmate.recommendation-results.v1` | FastAPI → Spring | key=request_id, `RECOMMENDATION_COMPLETED` 또는 `RECOMMENDATION_FAILED` |

`request_id`는 추천 한 번의 논리 식별자, `event_id`는 메시지 식별자입니다. 재전송은 저장된 동일 이벤트를 재사용합니다. Spring이 인증 사용자·세션·계획·Context 버전을 request_id에 연결하며 사용자 UID·JWT를 모델이 선택하거나 Kafka 결과만으로 소유권을 정하지 않습니다.

같은 request_id에 다른 질문·필터·모드가 오면 충돌입니다. 완료 이벤트의 Context 버전·질문·적용 필터·모드를 저장된 요청과 검증합니다. 알 수 없는 요청이나 지난 화면의 결과를 현재 요청에 자동 연결하지 않습니다.

### 4.2 요청 이벤트 예시

아래 JSON의 ID·시간·좌표·점수는 계약 설명용 예시이며 실제 관광 데이터나 평가 결과가 아닙니다.

```json
{
  "schema_version": 1,
  "event_id": "3e993547-e5aa-412c-b55b-46f1e4256260",
  "event_type": "RECOMMENDATION_REQUESTED",
  "request_id": "44d3f77c-0c9c-4f6e-855d-c9aa0ec773bc",
  "context_version": 4,
  "requested_at": "2026-10-25T14:00:00+09:00",
  "deadline_at": null,
  "query": "창경궁을 찾아줘.",
  "filters": {
    "region": "서울",
    "city": "종로",
    "category": null,
    "area": null,
    "exclude_place_ids": []
  },
  "ranking_mode": "RERANKED",
  "limit": 1
}
```

내부 ranking_mode는 명시 필수로 현행 `SEMANTIC_ONLY`, `RERANKED`를 사용합니다. 첫 비교에서는 현행 후보 최대 30·최종 limit 1~20·모델·전처리를 보존합니다. 기본 모드·후보 수 최적화는 별도 확정합니다.

area는 null 또는 아래 CIRCLE 구조입니다. 현행 Context의 500~10000m 검증과 lat/lon 의미를 유지하고 현재 미지원인 REGION을 자동 지원하지 않습니다.

```json
{
  "type": "CIRCLE",
  "center": {"lat": 37.5794, "lon": 126.9910},
  "radius_meters": 1000
}
```

Spring이 확정한 쿼리·조건만 전달하며 개인 기억·대화 전체나 인증 비밀값을 넣지 않습니다. deadline_at의 운영 기본값과 늦은 완료의 사용자 표시 정책은 미정입니다.

### 4.3 완료 이벤트 예시

items는 검색·리랭킹을 마친 순서입니다. 추천 카드와 계획 제안에 필요한 상세를 포함하며 원시 1024차원 벡터는 포함하지 않습니다.

```json
{
  "schema_version": 1,
  "event_id": "0c6927ad-8051-4717-9af0-b2c3ef8bec41",
  "event_type": "RECOMMENDATION_COMPLETED",
  "request_id": "44d3f77c-0c9c-4f6e-855d-c9aa0ec773bc",
  "context_version": 4,
  "status": "COMPLETED",
  "query": "창경궁을 찾아줘.",
  "completed_at": "2026-10-25T14:00:01+09:00",
  "ranking_mode_requested": "RERANKED",
  "ranking_mode_applied": "RERANKED",
  "rerank_status": "APPLIED",
  "fallback_reason": null,
  "applied_filters": {
    "region": "서울",
    "city": "종로",
    "category": null,
    "area": null,
    "exclude_place_ids": []
  },
  "candidate_count": 1,
  "returned_count": 1,
  "items": [
    {
      "place_id": 378,
      "rank": 1,
      "name": "창경궁",
      "description": "계약 설명용 장소 본문입니다.",
      "region": "서울",
      "city": "종로",
      "category": "관광지",
      "source_category": "고궁",
      "latitude": 37.5794,
      "longitude": 126.9910,
      "tour_content_id": "example-content-id",
      "image_url": null,
      "homepage_url": null,
      "semantic_score": 0.82,
      "rerank_score": 0.93,
      "source_version": 6,
      "latest_seen_version": 6,
      "index_config_version": "example-config-v1"
    }
  ],
  "warnings": []
}
```

이 예시의 1초 시간 간격이나 점수는 지연·정확도 측정값이 아닙니다. 실제 완료 이벤트에는 실제 실행 값과 스냅샷 메타데이터를 기록합니다.

| 필드 묶음 | 계약 |
|---|---|
| place_id·rank·items 순서 | 실제 DB 장소 ID와 최종 순위. 중복·순위 불일치 검증 |
| 이름·설명·지역·분류·좌표·이미지·홈페이지·출처 | 검색 복사본의 같은 source_version. 누락 정보는 null로 구분 |
| semantic_score·rerank_score | 실제 검색 모델 점수. 정답 관련도 0~3점·확률과 혼동하지 않음 |
| source_version·latest_seen_version·index_config_version | 추천에 사용한 스냅샷·최신 접수·모델/전처리 세대 |
| requested/applied 모드·rerank_status·fallback_reason | 실제 리랭킹·생략·대체를 구분 |
| warnings·처리 시간·모델 metadata | 실제 발생한 상태와 측정값. 임의 시간·근거 생성 금지 |

Spring은 이벤트 payload의 필수 필드·ID·개수·순위·유한 점수·적용 조건을 검증하고 같은 순서로 기존 camelCase DTO에 매핑합니다. 응답을 만들기 위한 장소 상세 SELECT를 추가하지 않습니다. 추천 결과가 최신 원본을 동기 확인한 것이라고 표시하지 않습니다.

### 4.4 작업·결과·발행의 원자성

1. Spring은 추천 요청과 요청 Outbox를 자신의 DB 트랜잭션에 저장하고 relay가 Kafka로 발행합니다.
2. FastAPI는 추천 요청을 자신의 DB에 영속 접수한 뒤 연속 접수 offset을 commit합니다. 중복 요청은 기존 작업·결과를 사용합니다.
3. 작업자는 쿼리 임베딩 → 필터 적용 Top-K → 모드별 리랭킹을 수행합니다. 본문·필터·이미지·벡터는 같은 source_version이어야 합니다. 추론 중 DB 연결을 점유하지 않습니다.
4. 완료 결과 payload와 결과 Outbox를 FastAPI DB의 같은 트랜잭션으로 저장합니다. 중복 작업·재시도가 서로 다른 완료 결과를 덮어쓰지 않게 상태·실행 세대를 조건부 검증합니다.
5. 결과 relay가 Kafka 발행 확인 후 Outbox를 갱신합니다. 확인이 불확실하면 저장된 동일 payload·event_id를 다시 보냅니다. 결과 재전송 때문에 모델 추론을 다시 하지 않습니다.
6. Spring은 원래 요청·Context와 대응을 확인하고 결과·수신 이벤트 ID·요청 상태를 자신의 DB 트랜잭션에 반영한 뒤 offset을 commit합니다.
7. 앱과 툴에는 이 영속 수신 결과를 전달합니다. 새 요청 이후 늦은 완료가 와도 현재 화면·계획을 덮어쓰거나 자동 저장하지 않습니다.

원본 변경 Outbox와 추천 요청 Outbox, 수신 기록과 요청 상태를 물리 테이블로 나누거나 공통 Outbox/Inbox로 구성하는 것은 구현 선택입니다. 두 서비스 DB를 넘는 분산 트랜잭션으로 묶지 않습니다. FastAPI DB에는 추천 요청·실행 상태·완료 payload·결과 Outbox의 논리 저장소가 추가로 필요합니다.

### 4.5 실패·빈 결과·취소 구분

| 이벤트·상태 | 의미 |
|---|---|
| COMPLETED, items 빈 목록·rerank_status EMPTY | 조회 가능한 인덱스에서 조건 내 후보 없음 |
| COMPLETED, SEMANTIC_ONLY·SKIPPED | 요청한 임베딩 순위 결과. rerank_score는 null |
| COMPLETED, 다른 applied 모드·fallback 이유 | 별도 허용 정책에 따른 대체 결과. RERANKED 성공과 분리 |
| RECOMMENDATION_FAILED | 처리 실패. error_code·실패 단계·재시도 가능 여부 포함. 빈 성공으로 바꾸지 않음 |
| 기한 만료·취소·이전 Context 결과 | 요청 상태와 실제 연산 상태를 구분하고 늦은 결과 처리 정책 적용 |

Kafka 접수 offset commit은 검색 완료가 아닙니다. 완료 이벤트 전달까지 별도 지연·실패가 생길 수 있습니다. 재시도 한도·처리 기한·실패 표시·취소 이벤트 정책은 미정이며 Kafka 적용만으로 임의 값을 고정하지 않습니다.

원본 수정·삭제가 아직 FastAPI DB에 반영되지 않았다면 응답은 과거 스냅샷일 수 있습니다. source_version과 색인 지연으로 이를 추적하고 최신성 요구와 허용 전파 지연을 별도 확정합니다. Spring이 추천 상세를 다시 조회하지 않는 결정은 유지하며, 계획 확정 시 필요한 소유권·계획 버전·필수 장소 조건 검증은 별도 책임입니다.

## 5. 두 DB·모델·Kafka 자원 관리

- Spring DB와 FastAPI PostgreSQL·pgvector DB는 별도 서비스입니다. 서비스별 접속 정보·계정·마이그레이션을 갖고 상대 DB 접근 권한을 부여하지 않습니다.
- FastAPI DB의 검색 조회 계정과 인덱싱·추천 작업·결과 Outbox 쓰기 계정을 역할에 맞게 나눕니다. 두 DB 사이의 ID는 논리 참조입니다.
- 모델·비동기 DB 풀·Kafka 클라이언트 수명을 관리합니다. 모델을 요청마다 로드하지 않고 동기 추론으로 Kafka poll·이벤트 루프를 막지 않습니다.
- 온라인 쿼리 처리·관광지 배치 임베딩·결과 전달의 대기열과 상태를 구분합니다. GPU 동시 실행·배치·토큰·큐 한도는 측정 후 확정합니다.
- lease·요청 기한 만료가 GPU 연산 종료를 보장하지 않습니다. 중복 실행은 작업 상태·실행 세대·원자적 완료 반영으로 보호합니다.
- 두 DB의 백업·초기 이관·재색인·결과 재전달 복구를 각각 검증합니다. 로그에 DB/Kafka 비밀값·JWT를 노출하지 않습니다.
- 현재 Compose의 Kafka·UI 기반 시설과 별도 DB·애플리케이션 구현 완료는 구분합니다. 새 추천 요청/결과 토픽의 초기화 연결도 후속 구현 대상입니다.

## 6. 관측과 검증

request_id로 Spring 접수 → 요청 발행 → FastAPI 영속 접수 → 검색·리랭킹 → 결과 Outbox → 완료 발행 → Spring 영속 수신을 연결합니다. 원본 색인은 event_id·placeId·source_version으로 추적합니다. 비동기 처리에는 별도 trace와 link를 사용할 수 있고 span ID와 trace ID를 구분합니다.

| 관측 항목 | 구분할 내용 |
|---|---|
| 원본 commit → 검색 복사본 반영 | 색인 전파 지연 |
| 추천 접수 → 완료 결과 수신 | 큐 왕복·작업 대기·추론·발행을 포함한 사용자 관점 처리 시간 |
| 리랭커 model_inference | 사용자 목표 약 0.5초 이하인 추론 구간 |
| 요청/결과 consumer lag, DB 작업 backlog, 각 Outbox 미전달 | offset commit 뒤 아직 끝나지 않은 작업도 관측 |
| 모드·버전·장치·정밀도·토큰·배치·실패·재시도·중복 | 품질·성능 재현 조건 |

평가기는 접수 응답이나 Kafka 발행 성공을 검색 완료로 취급하지 않습니다. 해당 request_id의 최종 추천 payload를 수신한 뒤 장소 목록·원문·순위·실제 처리 시간을 기록해야 합니다. 접수 HTTP 시간만 과거 동기 검색 전체 시간과 비교하지 않습니다.

품질 평가는 합의한 문항·검수표·@5/@10과 Precision·Recall·F1·MAP·NDCG·MRR를 유지합니다. 같은 데이터·인덱스·모델 세대로 비교하고 미반영·실패·늦은 결과를 숨기지 않습니다. 새 평가 범위·허용 품질 하락률·전체 응답 목표는 정하지 않습니다.

후속 검증 항목은 원본/Outbox 원자성, 두 DB의 독립 접속, 과거 버전·삭제·중복 이벤트, FastAPI 완료 저장 직후 장애, 완료 발행 확인 직후 장애, Spring 수신 저장 직후 offset commit 전 장애, 결과 중복·이전 Context·기한 만료, 상세 재조회 없이 필요한 모든 필드 구성입니다. 이번 문서 작업에서 이 애플리케이션 통합 검증을 실행한 것은 아닙니다.

## 7. 초기 이관과 남은 결정

기존 places 원본과 공개 ID를 보존하고, 별도 FastAPI DB에 버전 있는 검색 복사본을 초기 이관합니다. 검증된 기존 벡터는 재사용할 수 있으며 모델·전처리·원문 대응이 확인되지 않는 행은 재색인합니다. 초기 스냅샷과 실시간 이벤트는 버전으로 병합합니다.

원본 이벤트에 image_url·homepage_url·tour_content_id까지 포함해 결과 payload를 완성합니다. 같은 스냅샷으로 기존 검색 순위와 새 추천 결과를 비교한 뒤 앱·Context·툴 호출의 비동기 계약을 연결합니다. 전환 검증 전에 기존 컬럼·볼륨을 삭제하지 않습니다.

Kafka·UI는 현재 로컬 기반 시설입니다. 별도 FastAPI DB·추천 요청/결과 토픽·producer·consumer·결과 저장 연결은 로컬 Codex 구현과 대조할 대상입니다. 이번 변경은 문서이며 기존 Docker·앱 코드를 수정하지 않습니다.

운영 GPU·모델 정밀도·토큰·배치·후보 수, Kafka 운영 수치·재시도/DLQ, 결과·삭제 표식 보관, 원본 전파 지연 허용 기준, 앱 접수/진행/완료 수신 방식, 요청 기한·취소·fallback 정책은 확인 후 확정합니다.
