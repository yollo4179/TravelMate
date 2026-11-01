# Qwen 정확 토큰 가드와 계획 없는 검색 도구

기준 `794e7565`, 2026-11-02. 두 구현을 연결하고 모의 회귀와 저장 입력의 오프라인 토큰 계산을 수행했다. **실제 Qwen/GPT 추론·검색·임베딩·리랭킹·유료 호출·운영 DB 반영·배포는 0회**다. 로컬 모델은 어휘만 읽었으며 추론 context나 가중치 평가를 실행하지 않았다. 서버 메타데이터도 이번에는 재조회하지 않고 이전 저장본을 사용했다.

## 구현

### 1. Qwen 호출 가드

대화 루프와 `generate_plan`의 추가 LLM 호출이 공유하는 `OllamaLlmClient.complete()`에서 정확 계산기를 사용한다. 매 요청의 `/api/show`, `/api/version`, `/api/tags`와 전체 native wire 문자열을 별도 계산 프로세스에 전달한다. 시스템·이력·도구 정의·전체 원문·누적 도구 결과를 포함하며, 첫 요청 허용 여부와 관계없이 후속 요청을 다시 검사한다.

계산 프로세스는 검증한 Go renderer → native 어휘 tokenizer → 독립 BPE의 token-ID 비교 → 원문 바이트 복원 검사를 수행한다. manifest/model/template/renderer/DLL 해시, 서버 버전, tokenizer metadata·버전·특수 토큰 정책을 확인한다. 현재 검증한 Windows AMD64 / Ollama 0.40.13 / qwen3:8b / think=false 외의 프로필은 차단한다.

결과는 `EXACT_LOCAL_CROSSCHECKED`이며 실제 API 사용량과 구분한다. 가드의 출력 예약·context 비교는 유지했다. 계산기 미설정·미지원·해시 불일치·시간 초과·계산 실패는 `COUNT_UNAVAILABLE`, 입력+예약 초과는 `CONTEXT_LIMIT`로 추론 전에 차단한다. 원문 절단, context 증가, 보수적 계산으로 자동 복귀, 공급자 전환·유료 재시도는 없다. 기본 8192/1536은 유지했다.

현재 환경의 실행 명령 기본값은 `[]`이므로 **자동으로 실제 호출이 활성화되지 않는다**. 검증된 파일과 실행 명령을 평가 서버에 설정해야 한다. [설정·프로필·호출 경계](../../../../../docs/architecture/qwen-exact-runtime-counter.md)를 참조한다. 파일 해시·어휘를 매번 읽는 비용이 있고, 다른 플랫폼과 실제 서버 `prompt_eval_count` 비교는 남아 있다. 실행 중 모델 tag나 파일을 바꾸지 않아야 한다.

### 2. 계획 없는 독립 검색

`search_places`는 `ContextPlanningService.search()` 대신 공통 `PlaceSemanticSearchService.search(PlaceSearchRequest)`를 호출한다. `planningRequest` 없이 query만으로 실행할 수 있다. HTTP에는 기존 GET을 보존하고 `POST /api/places/search`를 추가했다.

```json
{
  "query": "아이와 갈 공원",
  "region": "서울",
  "city": null,
  "category": null,
  "excludePlaceIds": [378],
  "area": {
    "type": "CIRCLE",
    "center": {"lat": 37.5206092598, "lon": 127.1150682209},
    "radiusMeters": 500
  },
  "limit": 10,
  "rankingMode": "RERANKED"
}
```

query 외의 항목은 기본값/선택 조건이다. 공개 결과 수 1~20, 반경 500~10000m, 내부 후보·활성 근거 상한은 유지했다. 지역·도시·카테고리와 제외 ID·반경은 Spring service → Kafka filters → 기존 Python SQL로 전달된다. 제외·반경 조건은 Top-K 전에 적용된다. 거리 계산은 기존 Haversine이며 PostGIS나 실제 도보 시간으로 변경하지 않았다.

대화 요청에는 독립 `searchContext`를 추가했다. 계획의 날짜·체류시간·카페 개수를 요구하지 않는다. 도구의 nullable 필터는 명시된 searchContext를 상속하고, 서로 다른 조건은 `SEARCH_SCOPE_CONFLICT`로 거부한다. 제외 ID는 합집합으로 적용하고 출처를 기록한다. searchContext가 없고 기존 planningRequest가 있으면 **CIRCLE 범위만** `LEGACY_PLAN_AREA`로 명시해 연결한다. 검색 문장에 계획 themes 등을 자동으로 덧붙이지 않는다. 기존 계획 서비스의 검색·생성·초안 저장 경로는 그대로 보존했다.

도구 정의에는 query/limit/region/city/category/exclude_place_ids/area를 포함한다. nullable 항목도 스키마의 required에 넣어 strict 도구 형식을 유지하며, 실행기는 생략된 선택 조건의 기본값을 명시적으로 적용한다. 검색 결과 modelData에는 `searchContractVersion=place-search-v2`, 적용된 `searchCriteria`, `filterProvenance`, 후보·근거를 보낸다. 가짜 GeneratePlanRequest를 만들지 않는다.

`ContextPlanPromptFactory.assemble()`를 검색·계획이 공통 사용한다. 장소 ID, 전체 원문·출처·인용 위치, 귀속·관계·방향·조건, 부정·차단 기록은 보존하고 `generatedSupplement`는 구분한다. 기존 요약 문자열의 400자 제한을 원문 대체로 사용하지 않는다. 인용 ID와 quote의 소속 검증도 유지한다. 이것은 의미 정확성이나 과거 기록의 현재 유효성을 판정했다는 뜻은 아니다.

### 3. 평가 기록과 호출 제한

기존 관측의 raw `tool_calls`/arguments는 수정하지 않는다. 평가 변환본은 별도 `evaluation_tool_call_projections`에 `place-search-v2-to-frozen-v1` 버전으로 저장한다. 명시된 최종 검색 조건·출처, 옛 계약용 인자, 옛 인자 밖의 limit/rankingMode, 표현할 수 없는 category 조건을 구분한다. 상태는 `PROJECTED_NOT_SCORED`이며 옛 스키마 exact-args 통과를 자동 부여하지 않는다. 미전달 필터·이력을 관측 성공으로 만들지 않는다. corpus/config 검증과 실제 관측도 여전히 필요하다.

`mock-events.jsonl` → `mock-converted-records.jsonl`의 실제 Spring 모의 관측 변환을 포함했다. raw 호출 1개와 변환본 1개를 함께 보존하며 **모든 품질 coverage는 false**다. 모의 기록을 LIVE로 바꾸지 않았다. 비동기 Job/DRAFT를 옛 PLAN 계약으로 맞추지도 않았다.

B안 평가 서버에만 도구 허용 목록 `SEARCH_PLACES`, 모델 턴 2, 도구 호출 1, `tool-failure-policy=STOP`을 지정할 수 있게 했다. 기본 도구 세 개·6턴·8회·CONTINUE는 보존했다. 미등록 계획 도구와 잘못된 인자·검색 실패는 다음 모델 호출 전에 종료하며 복수·반복 도구 호출은 실행 전에 차단한다. 이는 서버 전역 공유 호출 예산이 아니다.

## 검증 결과

| 검증 | 결과 | 범위 |
|---|---:|---|
| 지정 Java 회귀 | 88 통과, 실패·오류·건너뜀 0 | 정확 가드, 프로세스 실패/시간 초과, 원문·인용, 단일 도구 루프, Job→DRAFT, 초안 검증, 독립 검색·B안 제한 |
| Python 회귀 | 28 통과 | worker 동일성/실패, 기존 trace 변환기, 기존 정확 토큰 검증 회귀 |
| Python SQL 모의 검사 | 1 통과 | 실제 SQL builder, 관계 검색 켬/끔 모두 지역·도시·제외·미터 반경을 Top-K 전에 적용 |
| 기존 검색 85문항 | 전부 런타임 DTO/service 통과 | 모의 client에 필터 전달, 검색 품질 평가는 아님 |
| 현재 B안 wire 8개 | 정확 계산·token-ID·바이트 검증 통과 | 첫 요청 4 + 모의 도구 결과 후속 4, 실제 API 사용량 없음 |
| 실제 worker 프로세스 | UTF-8 stdin/stdout 검사 통과 | 저장 메타데이터, 추론·모델 API 호출 없음 |

새 가드로 대체된 보수적 Qwen 전용 테스트는 정확 가드의 실패·초과 회귀로 교체했다. 기존 200문항 입력 준비 테스트는 계산기 미설정 상태를 모두 UNVERIFIED로 기록하며, 이전 상한 계산 결과를 새 구현의 관측으로 재사용하지 않는다. 동결 골든셋·manifest·이전 보고서는 수정하지 않았다. 이미 알려진 원본 작업 트리의 CRLF 차이와 LF 체크아웃 보존 검사 기록도 변경하지 않았다.

### 새 계약의 고정 모의 입력 토큰

아래는 동결 문항의 query·조건·이력을 새 서버 구조로 직렬화한 요청이다. 후보 결과는 원문·상충 검사용 **모의 A=101** 자료다. 해당 문항의 실제 검색 결과나 정답 corpus를 관측한 것이 아니다. 새 계약의 tool schema를 포함하므로 이전 853~933 토큰 측정값을 가져오지 않았다.

| case ID | 최초 입력 | 모의 도구 결과 후속 입력 | 후속 입력 + 출력 예약 1536 |
|---|---:|---:|---:|
| PLR-TM-palaces-01 | 936 | 2697 | 4233 |
| PLR-TM-palaces-03 | 959 | 2764 | 4300 |
| PLR-TM-palaces-04 | 985 | 2788 | 4324 |
| PLR-TM-family_parks-04 | 1029 | 2899 | 4435 |

모두 8192 이하다. 같은 native wire·template와 token-ID 해시를 `runtime-counts.jsonl`에 보존했다. 모델·DLL·renderer·manifest의 로컬 파일은 실제 해시를 확인했고, **서버 메타데이터는 이전 저장본**이다. 실제 실행 시에는 현재 서버의 동일성을 다시 검사한다. 실제 검색 원문 양이 다르면 후속 요청은 초과할 수 있으며, 그 경우 가드가 차단한다. 이 표는 실제 검색 후속 요청이나 실제 사용량의 사전 보장이 아니다.

## B안 실행 제안과 현재 가능 여부

**두 코드 경로는 연결됐고 모의 검증을 통과했다. 바로 실제 실행을 시작할 상태로 표시하지는 않는다.** 아직 실행 승인, 평가 전용 서버/DB, 정확 계산기 배포 설정, 현재 서버 동일성, corpus·장소 ID·검색 설정 일치와 실행 기록 수집 조건을 확인해야 한다. 운영 DB로 실행하면 안 된다.

- 대상: qwen3:8b, think=false, context 8192, 출력 예약 1536, RERANKED. GPT 앱 모델과 judge는 선택/실행하지 않는다.
- 문항: 위 네 development case ID만, 각 1회, 동시성 1, 재시도 0. 새 문항이나 잡담 문항은 넣지 않는다.
- 한도: API 요청 4개, Qwen 추론 최대 8회, 검색 도구 최대 4회, 계획 Job·계획 추가 LLM·judge 0회. 이 요청 목록 밖 호출은 실행자/하네스가 차단해야 한다.
- 최대 출력 예약 합은 12288토큰이며 실제 생성/과금 사용량이 아니다. 입력은 매 호출 전체를 다시 계산한다. 로컬 Qwen 외 외부 과금 공급자를 사용하지 않으며 embedding/rerank의 실제 내부 호출 수·비용·지연은 아직 관측하지 않았다. 실행 전에 로컬 구성과 추가 호출 여부를 고정해야 한다.
- 지연은 오프라인 계산기 측정만 `runtime-counts.jsonl`에 있다. 실제 추론·검색 지연과 전체 소요 시간은 미측정이다. 가드 계산 프로세스 제한은 90초, 기존 모델 read timeout은 240초, Kafka 검색 대기 한도는 120초이며 전체 배치 시간 보장으로 해석하지 않는다.
- 첫 동일성/계산/예산 실패, 미등록·복수·반복 도구 요청, 검색 오류/시간 초과, 근거 소속 오류, 누락된 관측, corpus/config 불일치, 계획 도구 시도, 위 호출 한도 도달 시 배치를 중단한다. 결과를 보충하려고 재실행하지 않는다.
- 관측/채점: 원본 tool_calls, 적용 필터, 검색 순위·근거, 서버 data와 LLM 설명, 종료·시간·실제 사용량을 각각 보존한다. 옛 계약 projection과 raw를 혼합하지 않는다. 랭킹은 corpus/qrels 일치 시만, 설명은 전달된 근거 범위에서 따로 검토한다. 옛 exact-args projection의 점수 사용은 별도 승인 전까지 하지 않는다.

로컬 미커밋 수집기 `collect_live.py`/`collect_holdout.py`와 runner/build를 먼저 읽고 해시를 남겼다. 기존 수집기는 검색 순위/holdout 용도이며 독립 대화의 원본 tool_calls·전체 루프 상한을 그대로 수집하는 도구는 아니다. 재사용 가능한 순위·입력 해시 연결은 유지하고 파일은 복사·덮어쓰기하지 않았다. 실제 B안은 인증된 평가 API와 현재 관측 필터를 사용하는 고정 네 요청의 수집 계획을 실행 전에 확인해야 한다.

계획 평가의 실제 이동시간·동선 최적화·운영시간·방문 비용·확정/수정/롤백 및 옛 PLAN 계약은 계속 미구현/미검증이다. 이번 모의 통과나 잡담으로 검색·계획 품질 평가 완료를 주장하지 않는다.
