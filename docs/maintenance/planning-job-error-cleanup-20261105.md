# 계획 작업 실패 사유 정리 (2026-11-05)

## 배경

수정 전에는 계획 생성 작업이 실패하면 모델 호출 단계의 내부 원인이 `planning_jobs.error_message`에 그대로 저장됐다.
내부 원인은 토큰 예산 검사, 영문 공급자·예산 오류 같은 것이다.
이 값은 작업 조회 API와 LiLi 후속 대사로 사용자에게 보인다.
v2 실측(`docs/evaluation/lili-router-v2-live-20261105.md`)에서 LiLi가 "토큰 예산을 확인하는 단계에서…"라고 말한 원인이다.

- 앞으로의 실패: 커밋 이후 `ContextPlanningService`는 모델 호출에서 난 모든 예외를 일반 안내 문구로 저장한다.
  내부 원인은 `PLAN_DRAFT` 관측 이벤트에만 남긴다.
- 이미 저장된 행: 아래 데이터 정정으로 바꿨다.

## 적용 내용

- SQL: `Docker/migrations/20261105_planning_job_user_facing_errors.sql`
  - 대상: `status='FAILED'`이면서 사유가 `LLM 호출 전 토큰 예산 검사 실패:`로 시작하거나 영문자로 시작하는 행
  - 새 값: `일정 생성 서비스가 잠시 응답하지 않아요. 잠시 후 다시 요청해 주세요.`
  - 서버 상수 `GENERATION_UNAVAILABLE`과 같은 문구다.
  - `updated_at`은 바꾸지 않았다. 작업 상태 변화가 아닌 문구 정정이기 때문이다.
- 새 DB에는 작업이 없으므로 초기화 스크립트(`docker-entrypoint-initdb.d`)에는 넣지 않았다.

| DB | 컨테이너 | 변경 행 | 작업 ID | 원래 값 |
|---|---|---|---|---|
| `travelmate_evaluation` (평가) | `tm-b-eval-springdb` | 1 | `6f1fe6ee-1af2-4ea1-8d1f-d29f48cb1268` | `LLM 호출 전 토큰 예산 검사 실패: COUNT_UNAVAILABLE` |
| `travel_db` (개발) | `travel-postgres` | 0 | – | 계획 작업 행 자체가 없었다 |

## 되돌리기

평가 DB의 한 행만 바뀌었다. 원래 값이 필요하면 아래 문장으로 되돌린다.

```sql
UPDATE planning_jobs SET error_message = 'LLM 호출 전 토큰 예산 검사 실패: COUNT_UNAVAILABLE'
WHERE job_id = '6f1fe6ee-1af2-4ea1-8d1f-d29f48cb1268';
```

이 작업은 평가 문항 `CONV-JOB-owned`이 조회하는 작업이다. 정정 뒤 같은 문항의 기대 동작은 LiLi가 일반 안내 문구로 실패를 전하는 것이다.

## 2차 정정 (같은 날)

- SQL: `Docker/migrations/20261105b_planning_job_draft_failure_messages.sql`
- 이유
  - 1차 문구 "일정 생성 서비스가 잠시 응답하지 않아요"는 확인하지 않은 원인(일시적 장애)과 재시도 효과를 단정했다. LiLi가 이를 장애 설명으로 읽었다. Codex 검수(`docs/evaluation/lili-v2-r3-agent-semantic-review-20261105.md`)의 지적이다.
  - 반복 실측(var2·var3)에서 검증기 문구 "인용이 해당 장소에 실제 전달한 원문 근거에 속하지 않습니다."가 그대로 저장됐다.
- 서버 기준(`ContextPlanningService.DraftFailure`)
  - 모델 호출 실패: `일정 초안을 만들지 못했어요. 같은 조건으로 다시 요청하거나 조건을 바꿔 요청해 주세요.`
  - 모델 초안이 서버 검사에 걸림: `만들어진 초안이 확인된 장소 정보와 맞지 않아 저장하지 않았어요. 다시 요청해 주세요.`
- 대상은 `operation='GENERATE'`인 실패 작업뿐이다. 사용자가 직접 고른 장소의 저장(`MANUAL`) 실패 사유는 사용자 입력에 대한 안내라 바꾸지 않았다.

| DB | 변경 행 | 작업 ID | 원래 값 |
|---|---|---|---|
| `travelmate_evaluation` | 5 | `6f1fe6ee-1af2-4ea1-8d1f-d29f48cb1268` | `일정 생성 서비스가 잠시 응답하지 않아요. 잠시 후 다시 요청해 주세요.` (그 전 값은 위 표) |
| | | `427774ef-5338-4253-818e-385817e9ce6e`, `948a6668-3046-4dbb-ab91-133b90e498ce` | `인용이 해당 장소에 실제 전달한 원문 근거에 속하지 않습니다.` |
| | | `93281865-bc03-4529-a1c7-f73dbda84229`, `a84720e3-775d-4c2d-a5b8-51ff6b2ed1fc` | `방문 체류시간이 여행 가능 시간을 초과합니다.` |
| `travel_db` | 0 | – | 실패한 계획 작업이 없었다 |

되돌리기:

```sql
UPDATE planning_jobs SET error_message = '일정 생성 서비스가 잠시 응답하지 않아요. 잠시 후 다시 요청해 주세요.'
WHERE job_id = '6f1fe6ee-1af2-4ea1-8d1f-d29f48cb1268';
UPDATE planning_jobs SET error_message = '인용이 해당 장소에 실제 전달한 원문 근거에 속하지 않습니다.'
WHERE job_id IN ('427774ef-5338-4253-818e-385817e9ce6e', '948a6668-3046-4dbb-ab91-133b90e498ce');
UPDATE planning_jobs SET error_message = '방문 체류시간이 여행 가능 시간을 초과합니다.'
WHERE job_id IN ('93281865-bc03-4529-a1c7-f73dbda84229', 'a84720e3-775d-4c2d-a5b8-51ff6b2ed1fc');
```

`CONV-JOB-owned`의 기대 동작은 이제 LiLi가 원인을 짐작하지 않고 "초안을 만들지 못했다"는 확인된 상태와 다음 행동만 전하는 것이다.
