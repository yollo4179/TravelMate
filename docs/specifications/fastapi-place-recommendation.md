# FastAPI 추천 API·DB 접근 명세

[추천 구조도](../architecture/fastapi-place-recommendation.md) · [문서 목록](../README.md) · [기존 투어 가이드 명세](personal-tour-guide.md)

작성일: 2026-10-25, 한국 시간. 코드 확인 기준: `f9f09db`. **아래 신규 API·모듈·환경변수는 구현용 계약 제안입니다. 문서 작성으로 실행 경로나 DB 권한을 변경하지 않습니다.**

## 1. 책임 경계

| 영역 | Spring Boot | FastAPI |
|---|---|---|
| 앱의 진입점 | 기존 공개 API와 인증 유지 | 내부 서비스 API |
| 사용자·계획·장기 기억 | 소유권 검증·조회·저장 | 검색에 필요한 정규화 조건 수신 |
| 검색 Context | 확정 지역·반경·제외·취향으로 요청 구성 | 전달된 명시 조건 적용 |
| 온라인 장소 추천 | 추천 클라이언트로 한 번 호출 | 쿼리 임베딩·DB 후보 조회·리랭킹·정렬 |
| DB 접근 | 기존 업무 테이블과 관광지 관리 | `places`의 검색 필요 컬럼 SELECT |
| 계획 변경 | 후보 검증·미리보기·사용자 확정·저장·롤백 | 검색 결과 반환 |
| 관광지 임베딩 생성 | 기존 배치의 원문 조회·벡터 UPDATE 유지 | 기존 `/embed`와 내부 임베딩 어댑터 |

FastAPI는 관광지 검색 서비스이지 사용자 DB 전체의 소유자가 아닙니다. 개인정보 원문·사용자 UID·계획 수정 권한 대신 필요한 조건을 전달합니다. 추천 파이프라인의 임베딩과 리랭킹은 내부 함수 호출이며 자기 HTTP 엔드포인트를 재호출하지 않습니다.

## 2. 기존 공개 API와 연결

| 진입점 | 전환 후 연결 |
|---|---|
| `GET /api/places/search` | 기존 인수 검증 → 추천 클라이언트 → 기존 `PlaceSearchResponseDto[]` |
| Context 기반 검색 | 기존 `PlanContext` 검증·의미 쿼리 구성 → 추천 클라이언트 |
| 계획 생성 후보 검색 | 동일 클라이언트로 후보 획득 → Spring의 기존 후보 검증·생성 처리 |
| `search_places` 도구 제안 | Spring 실행기가 확정 조건 주입 → 동일 클라이언트 |

현행 일반 검색은 공개 `limit` 1~20, 기본 10, `rankingMode` 기본 `RERANKED`입니다. 첫 이전에서 이 기본값을 몰래 바꾸지 않습니다. 운영 기본 모드와 fallback 정책의 변경은 별도 확정합니다.

현재 Context 검색은 `PlanContext.Area`의 `CIRCLE`만 지원하며 `REGION`은 거부합니다. FastAPI 이전만으로 지원 범위가 늘었다고 표시하지 않습니다. `exclude_place_ids`는 새 내부 계약에 명시하되, 공개 API·대화 Context에서 누락 없이 전달하도록 별도 연결이 필요합니다.

## 3. 내부 추천 API

`POST /internal/v1/place-search`

Spring에서만 호출하는 버전 계약입니다. 기존 일반 검색 응답은 Spring에서 호환 매핑합니다. 내부 서비스 인증과 `traceparent`를 전달하며, 앱 JWT·임의 SQL을 FastAPI에 위임하지 않습니다. 인증 방식·비밀값 배포는 실행 환경에서 확정합니다.

### 3.1 요청 예시

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

| 필드 | 계약 |
|---|---|
| `request_id` | Spring이 발급한 요청 추적 값. 인증·멱등 저장 키를 대신하지 않음 |
| `query` | 공백이 아닌 실제 의미 검색 입력. 이전 중에는 현행 Spring의 쿼리 구성 결과를 보존 |
| `filters.region/city/category` | 현재 DB 저장값과 일치하는 필터. null은 해당 필터 미지정 |
| `filters.area` | null 또는 아래 `CIRCLE` 구조. 좌표·반경 검증 후 기존 직선거리식 적용 |
| `filters.exclude_place_ids` | 제외할 BIGINT ID 목록. 모델 추론 전에 SQL에 적용 |
| `ranking_mode` | 내부 계약에서는 명시 필수. 현행 `SEMANTIC_ONLY`, `RERANKED` 사용 |
| `limit` | 최종 반환 수. 현재 공개 API에 맞춰 1~20 검증 |

반경 요청의 `area`는 다음 구조입니다. 기존 Context의 `lat/lon`을 그대로 사용하고 `longitude/latitude` 순서를 뒤바꾸지 않습니다.

```json
{
  "type": "CIRCLE",
  "center": {"lat": 37.5794, "lon": 126.9910},
  "radius_meters": 1000
}
```

기존 `PlanContext.Area.radiusMeters` 범위는 500~10000입니다. JSON snake_case 변환은 Spring 클라이언트 어댑터에서 처리합니다. 원문 대화·일기 전체를 붙이지 않고 Spring이 확정한 조건과 현재 쿼리를 전달합니다. 지역·제외 같은 필수 조건과 취향 같은 선호를 혼동하지 않습니다.

### 3.2 응답 예시

다음은 필드 구조를 보여주는 예시입니다. 점수와 시간은 실제 측정값으로 만들어 넣지 않았습니다. `items`가 비어 있으면 모델 호출 없이 정상 종료할 수 있습니다.

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

장소 항목은 DB 원문에서 가져온 다음 필드로 구성합니다.

| 내부 필드 | 기존 공개 응답 필드 | 의미 |
|---|---|---|
| `place_id` | `placeId` | 기존 `places.id` |
| `name`, `description`, `region`, `city`, `category` | 같은 camelCase 이름 | 관광지 원문. 생성형 문장으로 덮어쓰지 않음 |
| `source_category` | 현재 공개 DTO에는 없음 | Spring 내부 후보·기존 계획 프롬프트 호환에 사용 |
| `latitude`, `longitude` | 같은 이름 | 저장된 좌표, null과 0을 구분 |
| `semantic_score` | `semanticScore` | 현행 `1 - cosine_distance` 값 |
| `rerank_score` | `rerankScore` | 현재 CrossEncoder의 원점수. 확률로 해석하지 않음 |
| `tour_content_id`, `image_url`, `homepage_url` | `tourContentId`, `imageUrl`, `homepageUrl` | 기존 장소 메타데이터 |

- `SEMANTIC_ONLY`는 `rerank_score=null`, `rerank_status=SKIPPED`입니다.
- 실제 리랭킹 성공은 `rerank_status=APPLIED`입니다. 모드가 요청과 달라졌다면 `fallback_reason`을 반드시 기록합니다.
- 후보가 없으면 `rerank_status=EMPTY`이며 요청 모드를 그대로 표시합니다. 이것을 리랭킹 추론 성공 횟수에 포함하지 않습니다.
- 대체 순위 반환 허용 여부·예산은 미정입니다. 허용한 요청만 `ranking_mode_applied=SEMANTIC_ONLY`로 반환합니다. 평가에서는 대체 결과를 실제 리랭킹 결과와 분리합니다.
- 모델·검색 설정 버전, 단계 시간은 trace와 실행 메타데이터에 기록합니다. 공개 앱 응답의 필수 필드로 늘리지 않습니다.

Spring은 placeId 중복·응답 수·모드·적용 조건을 검증합니다. 계획에 추가할 때는 최신 DB에서 해당 장소의 존재와 계획 제약을 다시 확인합니다. 제안된 `candidateSetId`의 사용자·세션 연결은 Spring이 관리하며, FastAPI 응답의 request ID만으로 소유권을 판단하지 않습니다.

### 3.3 실패 구분

| 내부 응답 제안 | 의미 | 처리 |
|---|---|---|
| 200, `items=[]` | 조건 내 후보 없음 | 빈 성공으로 표시 |
| 422 | 입력·벡터 차원·지원하지 않는 범위 | 조건 오류를 명시, 조건 자동 완화 금지 |
| 503 | DB·필수 모델·추론 실행기 사용 불가 | 의존성 실패로 표시 |
| 504 | 요청 처리 기한 초과 | 대기·실행 상태를 별도 기록 |

Spring은 기존 오류 응답 규약으로 매핑합니다. 실시간 API 실패를 빈 검색 성공으로 바꾸지 않습니다. 이 상태 코드 표는 내부 신규 API 제안이며 현재 배포된 응답 코드가 아닙니다.

## 4. DB 연결·조회 계약

### 4.1 연결과 권한

| 항목 | 설계 |
|---|---|
| 접속 주소 | Docker 내부 `postgres:5432/travel_db`. FastAPI 컨테이너의 localhost를 DB 주소로 사용하지 않음 |
| 드라이버 제안 | SQLAlchemy 비동기 엔진 + asyncpg + pgvector 타입 어댑터 |
| 계정 제안 | `travelmate_search` 등 전용 조회 계정. 비밀번호는 로컬/운영 비밀값으로 전달 |
| 권한 | DB CONNECT·스키마 USAGE·`places` 검색 필요 컬럼 SELECT. 사용자·계획 테이블과 DDL·UPDATE 권한은 부여하지 않음 |
| 풀 관리 | lifespan에서 생성·종료. 풀 크기·대기 한도는 동시 요청 측정 후 확정 |
| 트랜잭션 | 후보 원문을 모두 읽고 연결 반환. 리랭커 대기·추론 중 연결 점유 금지 |
| 마이그레이션 | 기존 DB 관리 경로가 담당. FastAPI 시작 시 `create_all`이나 DROP 실행 금지 |

환경변수 이름 제안은 `SEARCH_DB_HOST`, `SEARCH_DB_PORT`, `SEARCH_DB_NAME`, `SEARCH_DB_USER`, `SEARCH_DB_PASSWORD`입니다. 운영 TLS 연결 옵션은 운영 DB 설정을 따릅니다. 계정 비밀번호·DB 연결 문자열·Authorization은 trace와 로그에 남기지 않습니다.

배포 시 전용 계정을 기존 볼륨에 적용해야 합니다. Docker init SQL만 추가하면 이미 초기화된 DB에는 실행되지 않습니다. 기존 `pgdata` 볼륨을 지우거나 `reset_schema.sql`로 계정 연결을 해결하지 않습니다.

### 4.2 후보 조회

1. 현재 BGE-M3와 동일한 모델·정규화 방식으로 쿼리 벡터를 만듭니다. 차원 1024·유한 값 여부를 확인합니다.
2. `places.embedding IS NOT NULL`과 현행 최소 유사도 0.0 조건을 보존합니다.
3. region·city·category·반경·제외 ID를 모두 **후보 LIMIT 전에** 적용합니다.
4. `embedding <=> query_vector` 오름차순으로 현재 최대 30개 후보를 읽습니다. 30은 현행 코드 값이며 최적값으로 확정한 수치가 아닙니다.
5. `SEMANTIC_ONLY`는 그 순서를 사용합니다. `RERANKED`는 같은 후보의 description으로 점수를 구해 정렬합니다. null 설명의 처리도 이전 경로와 비교해 명시합니다.
6. 최종 limit를 적용합니다. 리랭킹 점수 누락·개수 불일치·NaN은 실패로 처리합니다. 동점 정렬 규칙을 명시하고 평가에도 동일 적용합니다.

지역은 DB 저장값의 동등 비교입니다. 반경은 현재 SQL의 지구 반경 6371000m 기반 Haversine 직선거리식을 이전합니다. 도보 경로·이동시간·영업 여부를 이 검색으로 검증했다고 표시하지 않습니다.

아래는 `area=null`일 때의 조회 의미를 나타내는 SQL입니다. `:name`은 ORM 바인딩 표기이며 실제 실행 코드는 드라이버 타입 바인딩과 null 처리에 맞춰 구현합니다. 반경 요청에는 기존 좌표 검증과 거리 조건을 WHERE에 추가해야 합니다.

```sql
SELECT p.id, p.name, p.description, p.region, p.city, p.category,
       p.source_category, p.latitude, p.longitude,
       p.tour_content_id, p.image_url, p.homepage_url,
       1 - (p.embedding <=> CAST(:query_vector AS vector)) AS similarity
FROM places AS p
WHERE p.embedding IS NOT NULL
  AND 1 - (p.embedding <=> CAST(:query_vector AS vector)) >= :minimum_similarity
  AND (CAST(:region AS text) IS NULL OR p.region = CAST(:region AS text))
  AND (CAST(:city AS text) IS NULL OR p.city = CAST(:city AS text))
  AND (CAST(:category AS text) IS NULL OR p.category = CAST(:category AS text))
  AND NOT (p.id = ANY(CAST(:exclude_place_ids AS bigint[])))
ORDER BY p.embedding <=> CAST(:query_vector AS vector)
LIMIT :candidate_limit;
```

SQL 식별자는 코드에서 고정하고 사용자 입력은 바인딩합니다. 기존 `vector_cosine_ops` HNSW 인덱스를 재사용합니다. ANN 조회의 필터 후 후보 부족과 정확 검색 차이는 실행 계획·실제 후보 수로 검증하며, 조건 내 장소가 있는데 항상 충분한 수를 반환한다고 가정하지 않습니다.

### 4.3 관광지 임베딩 배치

온라인 요청은 쿼리만 임베딩하고, 관광지 벡터는 저장된 값을 사용합니다. 모든 관광지를 매 요청마다 재임베딩하지 않습니다.

현재 [ReembeddingService](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/domain/place/service/ReembeddingService.java)는 Spring이 원문을 읽고 FastAPI `/embed`로 배치 임베딩한 뒤 `places.embedding`을 갱신합니다. 이 이전에서는 그 호환 경로를 유지합니다. 배치까지 Python 작업자로 옮길 경우 쓰기 계정·작업 상태·재시도 계약은 별도 설계하며 온라인 조회 계정에 UPDATE 권한을 덧붙이지 않습니다.

임베딩 모델·전처리·차원을 바꿀 경우 기존 벡터와의 호환을 확인하고 재생성 작업을 별도 수행해야 합니다. DB 조회 위치 이전 자체는 모델 변경이나 전체 재임베딩을 요구하지 않습니다.

## 5. 추론 실행과 관측

- 모델과 DB 풀은 한 번 준비하고 종료 시 해제합니다. 요청별 모델 로딩은 금지합니다.
- 모델 연산은 제한된 실행기에 넘기고 비동기 HTTP·DB 이벤트 루프와 분리합니다. 모델별 동시 실행 수·대기열·요청 기한을 관측 가능한 설정으로 둡니다. 수치는 아직 미정입니다.
- 리랭커 기한 초과 후에도 GPU 연산이 진행될 수 있습니다. 실행 중인 작업을 완료 상태로 정리하기 전 슬롯을 다시 배정하지 않습니다. 끊긴 HTTP 요청만 보고 연산 자원이 비었다고 판단하지 않습니다.
- CUDA 프로필에서 실제 장치·정밀도·모델 버전을 기록합니다. CUDA 사용 불가를 조용히 CPU 성공으로 표시하지 않고 readiness·실제 적용 모드에 반영합니다.
- `/livez`는 프로세스 생존, `/readyz`는 DB·모델·구성 준비를 확인하는 신규 계약 제안입니다. 모드별 준비 상태를 노출해 임베딩 검색 준비와 리랭커 준비를 구분합니다. 매 healthcheck마다 무거운 리랭킹 추론을 실행하지 않습니다.

목표 trace 구조는 다음과 같습니다. Spring과 FastAPI는 W3C `traceparent`를 전달하고, 실제 모델 어댑터 호출도 같은 Context를 유지합니다.

```text
travelmate.search                         Spring 요청 전체
└─ recommendation.http                   Spring → FastAPI 한 번
   └─ recommendation.pipeline            FastAPI 검색 전체
      ├─ embedding.queue_wait
      ├─ embedding.model_inference
      ├─ database.pgvector_search
      ├─ reranking.queue_wait             RERANKED에만 존재
      ├─ reranking.model_inference        RERANKED에만 존재
      └─ response.serialization
```

| 기록 | 의미 |
|---|---|
| `request_id`, trace ID, span ID | 같은 요청 연결. trace와 span 식별자를 구분 |
| 요청·적용 모드, fallback 이유 | 실제 리랭킹과 대체 결과 구분 |
| 후보 수·반환 수·입력 토큰·유효 토큰·배치 크기 | 입력 규모와 패딩 비용 확인 |
| 모델 ID·revision·device·dtype·설정 버전 | 동일 조건 재현 |
| DB 풀 대기·SQL·모델 큐 대기·추론·전체 시간 | 느린 단계와 대기 구분 |
| 실패·취소·cold/warm 상태 | 성공 요청 평균만으로 지연을 숨기지 않음 |

리랭커 목표 약 0.5초는 **모델 추론 단계**에 대한 사용자 요청입니다. 평균·백분위·토큰·후보·배치 조건을 확정해야 수용 기준으로 사용할 수 있습니다. GPU 실행 시간을 정밀 비교할 때는 CUDA 비동기 실행과 완료 동기화를 고려합니다. HTTP 시간과 추론 시간의 차이를 순수 네트워크 지연이라고 표시하지 않습니다. 중첩 span의 시간을 더해 중복 호출 횟수나 전체 시간을 계산하지 않습니다.

현재 로컬 관측 코드와 GPU 반복 실행 결과는 사용자 전달 정보입니다. 분석한 GitHub 기준에 해당 코드가 모두 반영됐다고 가정하지 않습니다.

## 6. 개인화·도구 호출·계획 반영

1. Spring이 인증된 사용자의 이번 조건과 관련 취향을 구성합니다. 명시 취향 자동 저장·추론 취향 확인 정책은 기존 문서의 D-01을 유지합니다.
2. LLM의 `search_places` 인수를 Spring이 검증하고 확정 조건을 주입합니다. LLM이 owner UID·SQL·DB 연결을 선택하지 않습니다.
3. 추천 클라이언트가 FastAPI를 한 번 호출합니다. FastAPI는 확정 조건을 만족하는 실제 장소를 반환합니다.
4. Spring이 후보 집합을 사용자·세션·요청에 연결합니다. 도구 결과와 모델 선택은 placeId를 사용합니다.
5. 1개 추가·배치 계획 생성·빈자리 배정은 Spring에서 후보 검증과 계산을 수행합니다. API 위치 이전이 새 계획·자동 배정의 의미를 바꾸지 않습니다.
6. 대화 변경은 미리보기 후 음성·버튼 확정으로 적용합니다. 현재 기존 생성 API가 DRAFT를 저장하는 동작은 별도로 유지합니다.

## 7. 이전 검증과 남은 결정

| 검증 | 확인할 결과 |
|---|---|
| 같은 쿼리 벡터 | 모델·정규화·차원·전처리 일치 |
| 같은 DB·조건·후보 수 | 이전/이후 후보 ID와 점수·거리·제외 일치. ANN·동점 차이는 별도 확인 |
| 같은 후보의 리랭킹 | 후보별 점수와 최종 순서 비교 |
| 두 모드 | 실제 `SEMANTIC_ONLY`와 실제 `RERANKED` 결과를 각각 수집 |
| 기존 6개 지표 | 합의한 문항·검수표·@5/@10으로 Precision·Recall·F1·MAP·NDCG·MRR 비교 |
| 실패·조건·권한 | 제외/반경 위반 없음, 미지원 조건 명시, DB 실패와 빈 결과 구분 |
| 관측 | 요청 연결, 대기와 추론 구분, GPU 장치·정밀도 확인 |

이번 문서에서 새 평가 범위·성능 평균 기준·허용 품질 하락률은 정하지 않습니다. 운영 GPU, 리랭커 모델/정밀도/토큰/배치/후보 수, 서비스 인증, 기본 모드·fallback 정책·응답시간 한도는 구현 전에 필요한 항목별로 확인합니다.

첫 이전은 검색 책임 이동입니다. 이름·별칭 조회, 하이브리드 검색, RRF, 캐시 정책, 경량 모델은 후속 비교안이며 이 문서 작성만으로 새 기본 알고리즘이 되지 않습니다.
