# 두 궁궐 문항 실행: 서버 기동 첫 오류에서 중단

최신 `develop` 커밋 `9733756de571b54fe36ad3b52caf4ee64e8bcf5b`를 기존 격리 작업 트리에 fast-forward하고, 기존 소스 트리에서 오프라인 빌드를 한 번 수행했다. 빌드는 성공했지만 테스트 서버가 기동 중 실패해 두 문항은 모두 **NOT_RUN**이다. 검색→근거 준비→LLM 1회 경로는 이번 실행에서 검증하지 못했다. 기동 실패는 모델 품질 집계에서 제외한다.

## 첫 오류와 중단

2026-11-04 11:51:38.844 KST, `jwtTokenProvider` 초기화 중 아래 오류가 발생했다.

```text
PlaceholderResolutionException:
Could not resolve placeholder 'jwt.access-expiration' in value "${jwt.access-expiration}"
```

실행 시 기존 격리 `spring.properties`를 `--spring.config.location`으로 단독 지정했다. 이 옵션이 기본 설정 위치를 대체했으며, 지정한 파일에는 기본 설정에 있던 `jwt.access-expiration`이 없었다. 실행 명령 구성 오류로 서버가 시작되지 않은 것이다. 최신 코드의 검색·LLM 동작 오류로 판정하지 않는다.

첫 오류에서 중단한 뒤, 사용자가 최신 평가 서버 기동기를 통해 기동·인증부터 다시 확인하도록 지시했다. 그 후속 결과는 아래에 따로 기록한다. 추가 개발과 문항·모델 호출 재시도는 하지 않았다. 기존 격리 DB·Redis·Kafka·검색 서버를 재사용했으며 프로젝트·가상환경·런타임 사본은 새로 만들지 않았다. 최초 JAR는 기존 작업 트리의 `build/libs/`에서 직접 실행했다. 최초 기동은 기존 격리 연결을 명시한 `default` 프로필이며, 새 `evaluation` 프로필의 기동 검증 결과가 아니다.

## 후속 지시: 정식 평가 서버 기동기와 인증 사전 확인

기존 격리 연결값·키·모델 설정을 로컬 `.env.evaluation.json`의 `EVAL_*`에 연결했다. 이 비밀 설정 파일은 Git에서 제외한다. JWT 만료 시간을 임시 설정으로 하드코딩하지 않았으며 `spring.config.location`도 사용하지 않았다. 다음 명령을 1회 실행했다.

```powershell
python Evaluation/evaluation_server.py --environment-file .env.evaluation.json --start
```

기동기 자체의 설정 검사에서 다음 오류로 중단되었다.

```text
ValueError: Use a dedicated PostgreSQL database name ending in _evaluation
```

기존 격리 컨테이너 `tm-b-eval-springdb`에서 읽기 전용으로 확인한 DB는 `postgres`, `travelmate_b_spring`이다. 실제 기존 연결은 `jdbc:postgresql://127.0.0.1:55432/travelmate_b_spring`이며, 기동기의 `_evaluation` 접미사 조건을 만족하지 않는다. 존재하지 않는 DB 이름을 설정하거나 DB를 새로 만들거나 이름을 바꾸지 않았다. 검증 규칙도 수정·우회하지 않았다.

따라서 정식 기동기는 Spring 프로세스를 만들지 않았고, `aDMINuser`의 HTTP 인증은 **NOT_RUN_SERVER_UNAVAILABLE**이다. 인증 성공이나 평가 프로필 기동 성공으로 보고하지 않는다. 기존 DB 연결을 그대로 허용하는 기동기 검증 정책이 필요하며, 현재 지시의 추가 개발 금지 범위에서는 변경하지 않았다. 이 설정 검사 실패도 모델 품질 집계에서 제외한다.

원문은 [기동기 stderr](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/launcher.stderr.log), 상태·연결 대조 결과는 [launcher-preflight.json](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/launcher-preflight.json)에 있다.

## 문항별 결과

| 문항 | 원문 | 실행·원본 응답 | 설명·인용 일치 |
|---|---|---|---|
| `PLR-TM-palaces-01` | 창경궁을 찾아줘. | 미전송 / 응답 없음 | 평가 불가 |
| `PLR-TM-palaces-03` | 종로에서 조선 왕실 가족이 생활했던 궁이나 거처를 둘러보고 싶어. | 미전송 / 응답 없음 | 평가 불가 |

두 문항 모두 대화 제출 0회, 검색 0회, 근거 준비 0회, 토큰 계산 요청 0회, 추론 0회다. 추가 도구·일정 생성·judge·워밍업·재시도도 모두 0회다. 테스트 서버 기동은 1회이며 실패 후 종료되었다. 수집기와 provider 중계기는 실행하지 않았다.

## 단계별 지연

| 단계 | 관측 지연 |
|---|---|
| 앱 시작 로그 → 기동 실패 로그 | 3,647ms |
| 문항별 검색 / 근거 준비 / 토큰 계산 / LLM / 서버 턴 / 클라이언트 전체 | 모두 미관측 (`null`) |

3,647ms는 앱 로그 시각 차이이며 JVM 초기 구동·빌드 시간을 제외한다. 이를 문항 응답 지연이나 검색 성능으로 사용하지 않는다. 호출하지 않은 단계의 지연을 0ms로 만들지 않았다.

## 원본과 증거

실행 결과 폴더는 [20261104-02](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/)다.

- [오류 원문](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/first-error.json), [서버 stdout 원본](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/spring.stdout.log), [서버 stderr 원본](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/spring.stderr.log).
- [원본 문항 요청과 미전송 표시](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/original-requests.json), [호출 수·문항별 상태·지연](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/summary.json).
- [실행 명령](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/server-process.json), [소스·JAR·기존 설정·수집기 해시](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/provenance.json), [파일 해시](../../Evaluation/runs/contextual/conversation-grounding-two-case-v1/20261104-02/artifact-sha256.json).

대화 요청·provider 요청을 전송하기 전에 실패했다. 신규 관측 이벤트와 이번 실행의 추론 원장은 생성되지 않았다. 따라서 원본 응답이나 설명·인용 판정을 생성하지 않는다. 기존 평가 결과와 원장도 수정하지 않았다. 이번 반영에는 이 실행의 기록만 포함하며, 과거 미추적 실행 자료는 포함하지 않는다.
