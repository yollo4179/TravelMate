# 계획 없이 장소를 검색하는 계약 제안

기준 `95552e7f`. **제안이며 서버 구현·운영 API 변경이 아니다.** 검색을 재실행하지 않았다. 동결 골든셋·기존 검색 순위·상한·거리 계산·계획 검증 정책은 변경하지 않는다.

## 현재 결합의 원인

독립 검색 자체에는 일정의 시작/종료 시각·출발지·교통수단·체류시간이 필요하지 않다. 현재 대화 도구의 재사용 경계가 계획 DTO까지 포함하기 때문에 필요해졌다.

1. `ConversationRequest.planningRequest`는 선택 필드지만, 있으면 `@Valid GeneratePlanRequest`가 전체 PlanContext를 검증한다. 필수 area/origin/startAt/endAt/transportMode/objective/preferences/categoryRequirements/unknownHoursPolicy와 inputMethod/requiredStops가 함께 필요하다.
2. `SearchPlacesTool.execute()`가 planningRequest 없음을 거부한다. 검색 인자는 현재 query·limit뿐이다.
3. `ContextPlanningService.search(context, ...)`는 CIRCLE만 허용하고 계획 themes/additionalRequest를 검색 문장에 덧붙인다. region/city/category는 null로 넘긴다.
4. 선택 원문을 만들기 위해 `ContextPlanPromptFactory.prepare(GeneratePlanRequest, ...)`를 재사용하고 modelData의 request에도 계획 요청을 넣는다.

이것은 **DTO·서비스·근거 포맷의 결합**이다. 검색 경로가 전체 계획 생성 검증을 실행하는 것은 아니다. 예를 들어 WALK만 허용하는 정책·비용 검증 등은 generate 경로의 별도 검사이고, search는 area를 확인한다. DTO가 필수 정보를 요구하는 문제와 실제 검색/계획 제약 검사를 구분해야 한다.

반면 `PlaceSearchController`의 기존 **GET /api/places/search**는 query·region·city·category·limit·rankingMode만 받아 `PlaceSemanticSearchService`를 직접 호출한다. 이미 계획 없는 검색 기반이 있다. 대화 도구를 이 공통 검색 계층과 공통 근거 포맷에 연결하는 것이 제안의 핵심이다.

## 제안하는 입력 계약

기존 GET은 유지한다. area/exclusions가 필요한 구조화 요청에는 **POST /api/places/search**와 독립 `PlaceSearchRequest`/`PlaceSearchCriteria`를 제안한다. 검색 도구는 HTTP로 서버 자신을 다시 호출하지 않고 같은 검색 service를 사용한다.

```json
{
  "query": "창경궁을 찾아줘.",
  "region": "서울",
  "city": null,
  "category": null,
  "excludePlaceIds": [],
  "area": null,
  "limit": 10,
  "rankingMode": "RERANKED"
}
```

[제안 JSON Schema](../../Evaluation/proposals/plan-independent-place-search.request.schema.json). query만 필수다. 지역·원 범위가 없더라도 현재 일반 검색의 동작처럼 검색할 수 있다. 명시된 조건을 없애거나 임의의 중심/반경을 생성하지 않는다. “내 주변”의 기준이 없으면 기존 대화 LLM이 보완을 요청할 수 있고, 이동 전용 정규식이나 별도 의도 LLM을 추가하지 않는다.

| 제안 필드 | 의미·규칙 |
|---|---|
| query | 사용자의 검색 문장. 계획 themes를 자동으로 덧붙이지 않고 effectiveQuery와 원래 query를 구분 |
| region / city / category | 현재 검색 metadata의 정확한 필터. null은 해당 제한 없음 |
| excludePlaceIds | 양의 장소 ID 배열. 검색 Top-K 이전에 제외해야 함. 기존 Python SQL의 지원 경로를 Spring까지 연결하는 안 |
| area | 선택적 CIRCLE, center.lat/lon, radiusMeters. 기존 500~10000m 범위를 보존하는 안. PlanContext.Area와 독립 DTO |
| limit | 현재 공개 검색처럼 1~20, 기본 10. 내부 후보/활성 근거 상한을 변경하는 필드가 아님 |
| rankingMode | 기존 RERANKED/SEMANTIC_ONLY. 서버·평가 설정이며 LLM이 성능 비교를 임의 선택하지 않음 |

도보 이동 가능성·운영시간·일정의 카페 최소 개수 등은 검색 metadata filter로 충족됐다고 주장하지 않는다. category=카페로 검색하는 것과 전체 일정에 카페를 최소 2개 포함하는 것은 다른 조건이다. 원 반경은 직선 거리이며 실제 도보 경로/시간의 보장이 아니다.

현재 Python 공간 필터는 Haversine 식을 사용한다. 이번 제안에서 이를 PostGIS ST_DWithin으로 이미 구현했다고 표시하거나 새 거리 계산으로 바꾸지 않는다.

## 대화 도구 연결 제안

`ConversationRequest.searchContext`를 planningRequest와 독립시킨다. 사용자가 입력한 지역·제외·반경을 LLM에 구조화해 전달한다. 계획 없는 검색을 위해 가짜 날짜·출발지·빈 계획을 만들지 않는다.

도구 `search_places`의 다음 계약은 query와 nullable region/city/category/area, exclude_place_ids, limit을 받는 안이다. 공개 DTO의 camelCase와 도구/Kafka의 snake_case는 **명시적인 버전 어댑터**로 연결한다. GPT strict tool schema는 모든 정의 필드를 명시하고 optional 의미는 null/빈 배열로 표현하는 별도 검증이 필요하다. 여기서 그 서버 도구를 등록하지 않았다.

UI/서버가 준 searchContext와 도구 인자를 합치는 규칙도 공개해야 한다.

- 도구의 null은 searchContext의 명시적 조건을 상속한다. 아무 조건도 없으면 제한 없음이다.
- 양쪽 scalar/area 조건이 서로 다르면 `SEARCH_SCOPE_CONFLICT`로 보완을 요구한다. 임의로 한쪽을 덮어쓰지 않는다.
- 제외 ID는 양쪽의 합집합으로 유지하고 각 출처를 기록한다. 동일한 조건은 한 번 적용한다.
- 지역/도시/카테고리/원 범위는 기존 SQL처럼 AND로 적용한다. 지원하지 않는 교집합·주소 사전 변환을 구현됐다고 가정하지 않는다.
- 계획 화면의 범위를 검색 기본값으로 재사용하려면 명시적 legacy adapter와 출처 기록이 필요하다. 계획 문장을 검색에 몰래 덧붙이지 않는다.

공통 `PlaceEvidenceAssembler`를 추출하는 안이다. 검색 결과의 ID·전체 원문·source·귀속·관계/조건·인용 좌표와 generatedSupplement 구분을 유지하고, 계획 factory도 같은 assembler를 재사용한다. 검색용 modelData에는 searchCriteria와 후보/근거를 넣으며 GeneratePlanRequest를 요구하지 않는다. 원문을 description 400자만으로 대체하지 않는다.

## 기존 골든셋과 항목별 대응

V1.4.0 검색 문항 85개를 전수 조사했다. 아래 수는 모델 성공 수가 아니라 조건이 존재하는 문항 수다.

| 기존 입력/도구 항목 | 건수 | 현재 대화 도구 | 현재 독립 GET / Kafka·Python | 제안 대응 |
|---|---:|---|---|---|
| input.query / arguments.query | 85 | query에 계획 themes/additionalRequest를 추가 | GET query 전달 가능 | 원래 query 그대로, 변환 시 effectiveQuery 별도 기록 |
| conditions.region | 85 | 인자 없음, planning search가 null 전달 | GET→Kafka→Python 지원 | region 그대로 |
| conditions.city | 27 | 인자 없음, null 전달 | GET→Kafka→Python 지원 | city 그대로 |
| conditions.category | 0 | null 전달 | GET→Kafka→Python 지원 | category 지원 유지. 이 골든셋으로 category 필터 품질을 검증했다고 말할 수 없음 |
| exclude_place_ids | 19 | 인자 없음 | GET 입력 없음, Spring Kafka 요청은 항상 빈 배열. Python 제외 SQL은 있음 | excludePlaceIds→Kafka exclude_place_ids, Top-K 전에 적용 |
| area | 1 | 완전한 planningRequest가 있어야 CIRCLE 전달 | GET 입력 없음. Spring client의 area 변환과 Python 반경 SQL은 있음 | 독립 area, 계획 정보 없이 전달 |
| area.center.latitude/longitude | 1 | 계획 좌표가 있어야 함 | 내부 lat/lon | lat/lon으로 이름만 명시 변환 |
| area.radius_meters | 1 | 계획 radiusMeters 사용 | Kafka radius_meters | radiusMeters와 미터 단위를 보존 |
| area.center_place_id | 1 | 별도 검색 출처 필드 없음 | 중심 좌표 사용 | 좌표 출처 metadata로 보존. 필수 방문지·제외 장소로 바꾸지 않음 |
| area.distance_method | 1 | 계획이 도보 조건을 가져도 직선 범위 | 현재 Haversine | haversine_straight_line 의미를 유지, 도보 시간 주장 금지 |
| input.messages / conditions.conversation | 20 | history로 전달 가능 | GET은 이력 입력이 없음 | 대화에서는 동일 이력을 한 번 전달. 서로 다른 두 이력이 있으면 거부 |
| candidate_place_ids / corpus fixture | 85 | 실제 검색 후보와 별개 | 운영 corpus 일치 미확인 | 평가 harness 자료. 임의로 실제 DB 후보/정답으로 삽입하지 않음 |
| provided_contexts / persona / request_time | 문항별 | 현재 요청에 모두 연결되지 않음 | 검색 필터가 아님 | 전체 의미 평가의 입력 전달 범위를 따로 기록. 원문 fixture를 검색했다고 위장하지 않음 |
| limit | 동결 도구 스키마에 없음 | 현재 필수 1~20 | 공개 GET 기본 10 | 제안 기본 10을 실행 설정으로 기록. 구 스키마와 동일하다고 주장하지 않음 |
| rankingMode | 동결 도구 인자에 없음 | 기본 리랭킹 | 현재 GET 지원 | 기존 두 모드를 별도 동일 입력으로 비교하는 서버 설정 |

**65개**는 region/city/category 조건을 기존 GET으로 운반할 수 있다. 나머지 **20개**는 제외 ID 19개 또는 반경 1개를 전달할 경로가 부족하다. 이 65개도 corpus 일치·순위 품질·대화 이력·의미 정확성까지 확인한 문항은 아니다. 대화 search_places의 계획 의존성은 별도로 남아 있다.

[85개 case ID와 원래 입력 해시/조건 및 제안 요청](../../Evaluation/runs/contextual/exact-qwen-and-search-contract-v1/20261102-01/search-case-mapping.jsonl)을 보존한다. 모든 제안 요청은 독립 schema에 맞는지 오프라인으로 검사한다. 이는 실제 어댑터 구현이나 검색 품질 평가가 아니다.

동결 도구 스키마는 query/region/city/exclude_place_ids/area만 허용하며 additionalProperties=false이다. 현재 limit과 제안 category는 구 스키마에서 허용되지 않는다. 따라서 raw native tool_calls를 삭제·재명명해서 구 hard-args/schema 점수를 합격으로 만들지 않는다. 새 계약 버전과 명시적 평가 projection을 별도로 승인하고, 원본 호출과 effective filters를 함께 보존해야 한다. 기존 순위 지표는 corpus/조건이 같을 때 재사용할 수 있지만 미지원 관측은 null로 남긴다.

## 구현 시 완료 기준과 남는 계획 한계

향후 구현은 조건 DTO → 공통 검색 service → Kafka filters → 실제 원문/귀속 assembler → 도구 결과의 경로를 검사해야 한다. 계획 없이 query만 검색, region/city AND, 제외 Top-K 이전 적용, 원 반경 변환, 충돌 거부, 원문/부정/조건 유지와 실제 출처 소속을 모의 검증해야 한다. 기존 계획 검색/검증 경로의 회귀도 별도로 확인해야 한다.

계획 평가는 별도다. 현재 구현된 DRAFT 공통 검증(체류시간 합·카페 최소 개수·필수 장소·중복·범위)은 유지한다. 실제 이동시간·경로 최적화·운영시간·고정 방문 시각·방문 비용 검증·확정·일정 수정·롤백·before/after 상태 기록은 이번 검색 계약으로 완성되지 않는다. `generate_plan`의 Job→DRAFT를 기존 `create_plan`의 PLAN/applied/proposalId 계약으로 맞추지 않는다. 잡담 2건도 검색·계획 평가의 완료가 아니다.
