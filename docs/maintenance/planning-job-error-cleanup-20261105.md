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
