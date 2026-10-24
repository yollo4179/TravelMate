# 06. Server Place·TourAPI 리팩토링 변경 사항

> 작성일: 2026-07-22  
> 범위: Spring Boot `place` 도메인, TourAPI 수집·색인 파이프라인, OAuth 명명, Android 장소 검색 계약  
> 기준 스키마: `Docker/init/01-schema.sql`

## 1. 리팩토링 목표

기존 구조에서는 `place`, `tourAPI`, Kakao 장소 검색의 책임이 서로 겹쳐 보여 다음 내용을 판단하기 어려웠다.

1. 장소 검색의 기준 데이터가 Kakao인지 TourAPI인지
2. TourAPI가 독립 도메인인지 장소 데이터를 공급하는 외부 소스인지
3. JPA 저장소와 PGVector 검색 저장소가 왜 나뉘어 있는지
4. 수집, 변환, 임베딩, 저장을 어느 서비스가 담당하는지

이번 리팩토링은 **Place를 핵심 도메인으로 두고 TourAPI를 Place 데이터 공급원으로 배치**하는 방향으로 정리했다. 메인 검색은 DB에 저장된 TourAPI 장소를 대상으로 한 의미 기반 검색과 리랭킹을 사용한다.

## 2. 최종 역할 구분

| 영역 | 현재 역할 | 비고 |
|---|---|---|
| `domain/place` | 장소 검색, 장소 저장, 임베딩 갱신 등 핵심 장소 기능 | 애플리케이션의 중심 도메인 |
| `domain/place/source/tourapi` | TourAPI 원본 수집, 공통 Place 형식 변환, 임베딩 및 색인 | Place에 데이터를 공급하는 외부 소스 |
| `KakaoLocalApiClient` | Kakao Local 키워드 검색 호출 | 메인 검색에서는 제외하고 격리 보관 |
| Kakao Map SDK | Android 지도 렌더링 | 장소 데이터 수집과 별개의 기능이므로 유지 |
| OAuth 클라이언트 | Kakao·Google·Naver 로그인 토큰 변환 | 장소 검색 API와 무관 |
| `embedding-server` | 임베딩 생성 및 리랭킹 | Spring Boot 검색 파이프라인에서 호출 |

## 3. 장소 검색 흐름

```text
Android PlaceSearchApi
        │
        ▼
PlaceSearchController
        │ 요청 검증 및 응답 DTO 변환
        ▼
PlaceSemanticSearchService
        ├─ EmbeddingClient: 검색어 임베딩 생성
        ├─ PlaceSemanticSearchRepository: PGVector 후보 검색
        └─ RerankClient: 후보 의미 적합도 재정렬
        │
        ▼
PlaceSearchResponseDto
```

검색 엔드포인트는 `GET /api/places/search`를 유지한다. 지원 파라미터는 다음과 같다.

| 파라미터 | 필수 여부 | 설명 |
|---|---|---|
| `query` | 필수 | 자연어 장소 검색어 |
| `region` | 선택 | 광역 지역 필터 |
| `city` | 선택 | 도시·시군구 필터 |
| `category` | 선택 | 장소 카테고리 필터 |
| `limit` | 선택 | 반환 개수, 1~20, 기본값 10 |

후보 검색은 PostgreSQL의 PGVector 연산자를 사용하므로 `JdbcTemplate`을 유지했다. 이는 JPA가 나빠서가 아니라, 벡터 연산 SQL을 명확하게 제어하기 위한 선택이다.

## 4. Repository 책임 분리

기존 `PlaceVectorRepository` 한 클래스에 섞여 있던 기능을 용도별로 분리했다.

| Repository | 책임 |
|---|---|
| `PlaceSemanticSearchRepository` | 쿼리 벡터와 장소 벡터의 유사도 검색 |
| `PlaceCatalogRepository` | 정규화된 장소 저장 및 TourAPI 콘텐츠 ID 조회 |
| `PlaceEmbeddingRepository` | 재임베딩 대상 조회 및 벡터 갱신 |
| `PlaceDetailRepository` | TourAPI 장소 상세 정보 저장·조회 |
| `TourPlaceRawRepository` | TourAPI 원본 JSON 적재 및 처리 상태 관리 |

사용되지 않던 `PlaceJpaRepository`와 불완전한 `Place` JPA Entity는 제거했다. 현재 DB 구조는 `spring.jpa.hibernate.ddl-auto=none`이므로 Docker 초기화 스키마가 기준이며, 이번 리팩토링에서 스키마 변경은 하지 않았다.

## 5. TourAPI 수집·색인 파이프라인

기존 최상위 `domain/tourAPI` 패키지는 제거하고 다음 경로로 이동했다.

```text
domain/place/source/tourapi
├─ classification  분류 코드 조회
├─ client          TourAPI 목록·상세 HTTP 호출
├─ code            지역·콘텐츠 타입 Enum
├─ data            색인 전 TourPlaceCandidate
├─ mapper          원본 JSON 변환 및 검색 설명 생성
├─ repository      TourAPI 원본 저장
└─ service         수집·색인·트랜잭션 저장
```

전체 처리 순서는 다음과 같다.

```text
TourPlaceRawCollectionService
  TourAPI 호출 → 원본 JSON 저장
              │
              ▼
TourPlaceIndexingService
  미처리 원본 조회 → 매핑 → 배치 임베딩
              │
              ▼
TourPlacePersistenceService (@Transactional)
  places 저장 → 체험 프로그램 저장 → 원본 처리 완료 표시
```

클래스별 책임은 다음과 같다.

1. `TourPlaceRawCollectionService`: 외부 API에서 원본을 받아 스테이징 테이블에 저장한다.
2. `TourPlaceRawMapper`: 원본 JSON을 `TourPlaceCandidate`로 변환한다.
3. `TourPlaceDescriptionBuilder`: 의미 검색에 사용할 설명 문자열을 구성한다.
4. `TourPlaceIndexingService`: 미처리 데이터 조회, 배치 분할, 임베딩 호출을 조율한다.
5. `TourPlacePersistenceService`: 한 트랜잭션 안에서 정규화 장소 저장과 처리 완료 표시를 수행한다.
6. `TourPlaceDetailSyncService`: 필요한 시점에 TourAPI 상세 데이터를 동기화한다.

수집과 색인을 분리했기 때문에 외부 API 호출 실패, 임베딩 실패, DB 저장 실패의 위치를 이전보다 분명하게 확인할 수 있다.

## 6. Kakao 기능 정리

Kakao라는 이름이 서로 다른 세 기능에 사용되어 혼동이 있었다. 현재는 다음처럼 구분한다.

1. `KakaoOAuthClient`: Kakao 로그인 공급자 전용 OAuth 전략이다.
2. `KakaoLocalApiClient`: Kakao Local 장소 검색 전용 외부 API 클라이언트다.
3. Kakao Map SDK: Android 지도 표시 전용이다.

Kakao Local 기반 장소 일괄 수집과 일반 검색 서비스는 제거했다. 다만 향후 정확한 상호명 검색이나 현재 위치 주변 보조 검색에 사용할 가능성이 있어 `KakaoLocalApiClient` 자체는 독립 클라이언트로 남겼다.

## 7. OAuth 명명 변경

OAuth 전략 선택 구조는 유지했다. `OauthManager`가 `List<OAuthClient>`를 주입받고 각 구현체의 `supports(provider)` 결과로 알맞은 전략을 선택한다.

모호했던 구현체 이름만 다음과 같이 변경했다.

| 이전 | 변경 |
|---|---|
| `KakaoClient` | `KakaoOAuthClient` |
| `GoogleClient` | `GoogleOAuthClient` |
| `NaverClient` | `NaverOAuthClient` |

따라서 Kakao OAuth와 Kakao Local 장소 검색이 클래스 이름만으로도 구분된다.

## 8. Android 검색 계약 변경

Android에서도 Kakao에 종속된 이름을 서버의 일반 장소 검색 계약에 맞게 변경했다.

| 이전 | 변경 |
|---|---|
| `KakaoQueryApi` | `PlaceSearchApi` |
| `KakaoQueryRepository` | `PlaceSearchRepository` |
| `PlaceResponse` | `PlaceSearchResponse` |

`PlaceSearchResponse`는 장소 기본 정보 외에 `semanticScore`, `rerankScore`, TourAPI 콘텐츠 ID, 이미지 URL, 홈페이지 URL을 받을 수 있도록 서버 응답과 맞췄다.

현재 단계는 네트워크 계약과 ViewModel 컴파일까지이며, 지도 화면에서 검색 결과를 마커와 연결하는 UI 작업은 아직 남아 있다. 이 작업 전까지 Android Studio를 반드시 실행할 필요는 없다.

## 9. 제거·이동된 주요 구성요소

### 9.1 제거

- `PlaceCollectorService`: Kakao 기반 장소 일괄 수집
- `PlaceSearchService`: Kakao Local을 직접 사용하던 일반 검색
- `PlaceVectorRepository`: 여러 DB 책임이 집중된 저장소
- `PlaceJpaRepository`, `Place` Entity: 실제 흐름에서 사용되지 않던 JPA 구성
- 최상위 `domain/tourAPI`: Place 외부 소스 패키지로 대체

### 9.2 이동 또는 이름 변경

- `KakaoLocalService` → `KakaoLocalApiClient`
- `TourApiListClient` → `TourApiPlaceListClient`
- `TourApiDetailClient` → `TourApiPlaceDetailClient`
- `TourApiRawCollectorService` → `TourPlaceRawCollectionService`
- `TourPlaceProcessorService` → `TourPlaceIndexingService`
- `PlaceDetailSyncService` → `TourPlaceDetailSyncService`
- `LclsSystmCodeLookup` → `LclsSystemCodeLookup`

## 10. 기존 검증 기록 (작성 당시)

다음 비파괴 테스트와 빌드를 통과했다.

1. Spring 애플리케이션 컨텍스트 로딩 테스트
2. 임베딩 서버 연동 테스트
3. 리랭커 클라이언트 테스트
4. 장소 의미 검색 서비스 테스트
5. Android `testDebugUnitTest`

확인 당시 임베딩 서버는 `localhost:8000`에서 정상 응답했으며 임베딩 차원은 DB 스키마와 동일한 1024였다.

TourAPI 원본 수집 및 색인 통합 테스트는 실제 외부 API 할당량과 DB 데이터를 변경하므로 이번 검증에서는 실행하지 않았다.

## 11. 현재 구현 단계

| 단계 | 상태 |
|---|---|
| TourAPI 원본 수집 | 구현 완료 |
| 원본 데이터 정규화 및 설명 생성 | 구현 완료 |
| 배치 임베딩 및 PGVector 저장 | 구현 완료 |
| 벡터 유사도 후보 검색 | 구현 완료 |
| 리랭커를 이용한 최종 재정렬 | 구현 완료 |
| Spring 검색 API 노출 | 구현 완료 |
| Android 검색 DTO·Repository 연결 | 구현 완료 |
| Android 지도 검색 UI 연결 | 미구현 |
| 실패 데이터 재처리 정책 | 보완 필요 |
| 운영용 DB 마이그레이션 도구 | 미도입 |

현재 백엔드는 **의미 검색과 리랭킹을 실제 API로 제공할 수 있는 단계**다. 전체 앱 기준으로는 Android 지도 UI에 검색 결과를 표시하고, 검색 결과 선택을 핀·여행 계획 흐름과 연결하는 작업이 다음 단계다.

## 12. 다음 권장 작업 순서

1. Android 검색 화면에서 `PlaceSearchRepository`를 호출하고 로딩·오류·빈 결과 상태를 표현한다.
2. 검색 결과 선택 시 Kakao Map 카메라 이동과 마커 표시를 연결한다.
3. 선택 장소를 핀과 여행 계획에 추가하는 서버 API 흐름을 연결한다.
4. 리랭커 장애 시 벡터 검색 결과를 반환하는 fallback 정책을 추가한다.
5. TourAPI 파싱 실패 원인과 재시도 횟수를 저장해 동일 원본이 계속 재처리되는 문제를 막는다.
6. Flyway 또는 Liquibase를 도입해 `Docker/init/01-schema.sql`, reset 스키마, 운영 스키마의 변경 이력을 하나로 관리한다.
7. 외부 API와 DB를 변경하는 통합 테스트를 별도 프로필·태그로 분리한다.

## 13. 관련 문서

- [최종 화면 구조](./travel_app_screen_structure.md)
- [RAG 검색 품질 분석](./rag_search_quality_analysis.md)
- [근처 검색 도구 설계](./nearby_search_tool_design.md)
- [쿼리 메타데이터 분리 분석](./query_metadata_separation_analysis.md)

## 14. 2026-10-12 코드 대조 및 재검증

현재는 장소 검색 백엔드와 Android 네트워크 계층이 구현된 단계이며, 최종 화면 기획의 사용자 흐름은 아직 연결되지 않았다. 구현 여부와 실행 검증 여부를 구분한다.

| 영역 | 코드 확인 결과 |
|---|---|
| TourAPI 수집·색인 | 원본 저장 → 변환 → 배치 임베딩 → 트랜잭션 저장 구현 |
| 장소 검색 | query 임베딩, 지역·도시·카테고리 SQL 필터, 후보 30개 리랭킹, REST 응답 구현 |
| Android 검색 | PlaceSearchApi → Repository → SearchViewModel 구현. 화면에서 결과 수집·마커 갱신 연결 필요 |
| 지도 | MapContent의 기본 지도·초기 핀·길게 누르기 콜백 존재. 핀 변경 시 갱신과 검색 결과 연결 필요 |
| 여행 계획·핀 활동 | 생성·검증·저장 서비스 존재. 최종 화면 흐름과 전용 API 연결은 별도 작업 필요 |
| AI 채팅·일정 화면 | ChatScreen, SchedulesScreen, DetailedPlanScreen 및 currentEditingPlan 공유 흐름 미구현 |
| 근처 검색·도구 호출 | 거리 검색과 검색 도구 라우팅은 설계 단계. LlmClient는 현재 텍스트 생성 인터페이스만 제공 |
| AI 대화 영속화 | 저장 방식 검토 문서는 있으나 AI 대화 세션·메시지 저장 흐름은 미구현 |

문서 해석 시 다음 차이에 유의한다.

- 4장의 스키마 변경 없음은 리팩토링 자체에 대한 기존 설명이다. 이번 누적 변경에는 두 SQL 파일의 `tour_api_raw` 테이블과 미처리 인덱스 추가가 포함되어 있다. 기존 DB에 자동 적용되는 마이그레이션은 없다.
- 검색 품질·근처 검색 설계 문서의 리랭커 도입 제안은 현재 코드에 반영됐다. 실제 거리 기반 검색과 자연어에서 필터 인자를 자동 추출하는 도구 호출은 남아 있다.
- 검색 API의 리랭킹이 계획 생성 서비스 전체에 적용된 것은 아니다. PlanGenerationService는 벡터 검색 저장소를 직접 호출한다.
- FastAPI 모델은 모듈 import 시 초기화된다. AGENTS.md의 lifespan 관리와 엄격한 타입 힌트 규칙에 맞추는 보완이 필요하다.
- 리랭커 장애 fallback, 수집 실패 재처리 정책, DB 마이그레이션 도구, 외부 의존 통합 테스트 분리가 남아 있다.

이번 실행 결과:

| 검증 | 결과 |
|---|---|
| Spring compileJava / compileTestJava | 성공 |
| Android testDebugUnitTest | 성공, 기존 캐시 재사용. 보고서상 기본 예제 테스트 1건으로 기능 검증 범위는 제한적 |
| Python compileall (app, routers) | 성공. 모델 추론 및 HTTP 동작 검증은 아님 |
| EmbeddingTest / PlaceSemanticSearchServiceTest / RerankClientTest | 총 3건 실패. 외부 임베딩·리랭커 HTTP 연결 실패(ResourceAccessException / ConnectException) |
| TourAPI 수집·색인 통합 테스트 | DB 변경과 외부 API 호출을 수반하여 이번에는 실행하지 않음 |

10장의 과거 통과 기록은 이번 환경의 통과 결과를 뜻하지 않는다. 임베딩·리랭커 서버 연결을 복구한 후 세 연동 테스트를 다시 실행해야 한다.

다음 구현 순서는 검색 결과 지도 표시 → 임시 핀 및 편집 상태 공유 → 상세 계획 확정·저장 → AI 채팅·검색 도구 호출 연결이 적절하다.

Git Flow 작업 경로는 `main → develop → feature/place-semantic-search`로 구성한다. 기능 브랜치는 검토 후 develop에 통합하고, 배포 준비가 끝난 변경을 release 단계에서 main에 반영한다. Android의 `app/debug.keystore`와 `.env`는 로컬 설정으로 제외되므로 새 환경에서는 별도 준비가 필요하다.
