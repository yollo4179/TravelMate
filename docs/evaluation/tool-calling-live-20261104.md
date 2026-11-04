# 기본 9사례 실제 툴콜링 평가 (2026-11-04)

`conversation-smoke-v1`의 9사례를 실제 모델로 실행한 기록이다. 판정 대상은 도구 선택, 도구 실행, 응답 계약이다.
추천 품질 평가가 아니다.

- 결론: **자동 검사 통과 2/9. 종료 기준을 충족하지 못해 "기본 9사례 툴콜링 연결 검증 완료"로 닫지 않는다.**
- 도구가 필요한 3사례에서 모델이 도구를 한 번도 호출하지 않았다. 되물어야 하는 1사례에서는 `generate_plan`을 잘못 호출했다.
- 모델 호출 10회, 추론 비용 상한 $0.0482(캐시 할인 미반영). 입력 토큰 계산 요청 비용은 확인하지 않았다(`ALLOW_UNVERIFIED`).
- 의미 검수(`review.csv`)는 아직 하지 않았다. 아래 판정은 자동 검사 기준이다.

## 1. 실행 환경

| 항목 | 값 |
|---|---|
| 기준 커밋 | `develop` `d54a76de` 위의 작업 트리. 이 문서와 함께 커밋한 평가기·예산 수정이 실행에 반영됐다 |
| 인프라 | B안 컨테이너 재사용(`travelmate-b-eval`). 기존 B안 DB를 복제한 평가 전용 DB 2개(`travelmate_evaluation`, `travelmate_search_evaluation`)와 전용 계정 `tm_evaluation`. 기존 B안 DB는 수정하지 않았다 |
| Spring | 평가 프로필 `bootRun`, 소스 해시 `514187e6…`(작업 폴더와 일치) |
| 검색 | 현재 저장소를 마운트한 B안 검색 컨테이너, CUDA, 소스 해시 `e5360b5d…`(일치). `compose.common-evaluation.yaml` 적용 |
| 검색 설정 | 운영과 동일: `chunk-only`, 장소당 근거 1, 리랭크 배치 32. 원문 근거 `post-retrieval-field-v1`(묶인 장소 311·378) |
| 모델 | `gpt-5.4-mini-2026-03-17`, `JSON_SCHEMA_V1`, `STRICT_TOOLS_V1`, reasoning `DISABLED`, 상한 6턴·8도구 |
| 계정 | 평가 DB의 기존 `aDMINuser`(`ROLE_BASE`). 토큰은 서버의 `JwtTokenProvider`와 평가 전용 비밀키로 실행 직전에 발급했다 |
| 예산 | 승인 정책 3개(A 묶음, 일정 생성, Job 조회). 재시도 없음, judge 없음 |

## 2. 문항별 결과

| 사례 | 실행 기록 | 자동 판정 | 모델 도구 호출 | 실패 검사 | 전체 / 사전 검색 / 추론 (초) | 토큰 입력/출력 |
|---|---|---|---|---|---|---|
| `PLR-TM-palaces-01` | `live-a-04` | 실패 | 없음(기대: 없음) | completed, message_source, citations, message_preserved, intent_preserved, citation_count | 17.4 / 11.5 / 4.9 | 6087/368 |
| `PLR-TM-palaces-03` | `live-a-05` | 실패 | 없음(기대: 없음) | completed, message_source, citations, message_preserved, citation_count | 29.8 / 25.7 / 3.2 | 5933/321 |
| `CONV-SOCIAL-thanks` | `live-a-06` | 통과 | 없음(기대: 없음) | - | 35.9 / 32.7 / 2.3 | 5144/62 |
| `CONV-CLARIFY-plan` | `live-a-06` | 실패 | `generate_plan {}`(기대: 없음) | model_tool_selection 등 8개 | 6.1 / 3.9 / 1.2 | 4930/14 |
| `CONV-CLARIFY-job` | `live-a-07` | 실패 | 없음(기대: 없음) | intent_type | 6.0 / 2.6 / 2.4 | 5112/98 |
| `CONV-UNSUPPORTED-booking` | `live-a-08` | 통과 | 없음(기대: 없음) | - | 6.7 / 4.0 / 2.2 | 4875/164 |
| `CONV-SEARCH-exclude-first` | `live-a-09` | 실패 | 없음(기대: `search_places`) | model_tool_selection, tool_arguments 등 5개 | 6.0 / 3.7 / 1.7 | 4882/122 |
| `CONV-PLAN-create` | `live-b-01` | 실패 | 없음(기대: `generate_plan`) | model_tool_selection 등 10개 | 28.5 / 24.8 / 2.6 | 6490/315 |
| `CONV-JOB-owned` | `live-b-02` | 실패 | 없음(기대: `get_planning_job`) | model_tool_selection 등 7개 | 36.1 / 31.9 / 2.8 | 5159/118 |

모든 모델 호출에 도구 정의가 포함됐다(관측 `coverage`의 `tool_definitions`). 실행 기록 폴더는 `Evaluation/runs/conversation-smoke/20261104-*`다.
"전체"는 평가기가 잰 대화 HTTP 시간이다. 완성 JSON 응답 방식이라 첫 토큰 시간은 측정하지 않았다.

## 3. 발견 사항

1. **필요한 도구를 호출하지 않는다.**
   - 첫 후보 제외: 기존 후보로 직접 다시 추천했다. 제외 검색이 실행되지 않았다.
   - 일정 생성: "초안 생성을 요청하기에 적합합니다"라고 답했지만 `generate_plan`을 호출하지 않았다. Job이 만들어지지 않았다.
   - Job 조회: 실제 Job ID를 받고도 "상태 조회 기능이 아니라 장소 검색 결과만 들어와 있다"고 답했다.
   - 사전 검색 근거가 있는 상태에서 직접 답하려는 경향으로 보인다. 원인은 아직 확인하지 않았다.
2. **조건 없는 일정 요청에 `generate_plan`을 호출했다.** 프롬프트의 "조건이 없으면 먼저 되물어라"를 따르지 않았다. 서버가 `planningRequest` 없음으로 실행을 거부해 일정은 생성되지 않았다.
3. **인용 하나의 오류로 답변 전체가 거부된다.**
   - 근거가 붙지 않은 다른 후보의 장소 설명을 인용했다(palaces-01: 창경궁 홍화문 379, palaces-03: 창덕궁 낙선재 380·건청궁 10).
   - 원문의 공백 2칸을 1칸으로 옮겨 적어 정확 일치에 실패했다(PLAN-create).
   - 서버는 `INVALID_RESPONSE`로 대체 문구를 반환했다. 올바른 인용과 설명까지 함께 버려진다.
4. **의도 값 오류.** CLARIFY-job은 도구 없이 되묻는 방향은 맞았지만 PLAN이 아닌 의도를 반환했다. "아직 접수된 작업이 없어 보인다"는 확인할 수 없는 단정도 포함됐다(의미 검수 대상).
5. **사전 검색 지연 편차가 크다.** 2.6~32.7초이며 24초 이상이 4건이다. 원인은 확인하지 않았다.

## 4. 실행 중 고친 것과 기준에서 벗어난 점

- `live-a-01`: 토큰 도구의 표준 출력에 `JwtTokenProvider`의 INFO 로그가 섞여 헤더가 거부됐다. 대화 요청 0회.
  - 그 로그에 평가용 JWT 비밀키(base64)가 들어 있어 `summary.json`의 실패 상세를 가렸고, 평가용 비밀키를 교체했다.
  - **기존 코드 문제:** `JwtTokenProvider.init()`이 서버 시작 때마다 비밀키를 INFO 로그로 남긴다. 운영 로그에도 남으므로 별도 수정이 필요하다.
- `live-a-02`: 평가기의 소스 해시가 Windows에서만 서버와 달랐다. Windows `Path`는 대소문자를 무시해 정렬하고, Gradle은 문자열을 대소문자 구분으로 정렬한다. 대화 요청 0회. 경로 문자열 정렬로 고쳤다.
- `live-a-03`: 원문 근거를 운영 기본값(꺼짐)으로 둔 상태의 palaces-01. 인용 가능한 근거가 없어 모델이 `evidence-378` 같은 ID를 지어냈고 거부됐다.
  - 이후 원문 근거를 켜고(`post-retrieval-field-v1`, 묶인 장소는 기존 2곳 그대로), 운영 스택 기본값도 같게 바꿨다.
- 평가 기동기가 Windows에서 `gradlew.bat`을 찾지 못하던 문제, 검색 기동기가 Spring과 같은 DB를 요구하던 규칙(운영은 DB 2개)을 고쳤다.
- **첫 실패 시 중단** 규칙을 유지했다. 실패 뒤 남은 문항은 사용자 결정에 따라 별도 실행으로 이어서 모았다(`live-a-05`~`09`). 같은 사례를 다시 실행한 것은 palaces-01(`03` → `04`, 설정 변경 후)뿐이다.
- **Job 조회 사례의 Job:** 일정 생성 사례가 Job을 만들지 않아, 같은 계획 조건으로 계획 API(`POST /api/v1/plans/generations`)에 직접 접수했다(`6f1fe6ee-…`).
  - 이 Job의 계획 생성 호출은 문항에 묶여 있지 않아 예산 검사에서 모델 호출 전에 실패했다(FAILED, 비용 0).
  - 일정 생성 사례의 비동기 계획 호출은 예산 정책에 `maxPlanGenerationCalls`가 있을 때만 허용하도록 바꿨다. 이번에는 Job이 생성되지 않아 사용되지 않았다.

## 5. 다음 단계

1. 도구 미호출·오호출 원인 확인(프롬프트, 사전 검색 근거 제시 방식, 도구 노출 조건).
2. 인용 검증 처리 방식 결정: 틀린 인용만 제외할지, 공백 정규화를 허용할지, 근거 없는 후보 설명을 어떻게 안내할지.
3. 사전 검색 지연 원인 확인.
4. 수정 후 같은 9사례를 새 예산 원장으로 다시 실행하고, 의미 검수까지 마친 뒤 종료 기준을 다시 판정한다.
