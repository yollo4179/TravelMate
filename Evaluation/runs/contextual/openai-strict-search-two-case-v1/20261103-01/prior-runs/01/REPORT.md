# OpenAI strict 기존 2문항 실행 결과

첫 문항의 토큰 계산 단계에서 실패하여 중단했다. 모델 성능을 평가한 결과가 아니다. 자동 수정·재실행·추가 문항은 수행하지 않았고, 전용 평가 Java 프로세스도 종료했다.

## 설정과 가드

- 모델: `gpt-5.4-mini-2026-03-17`
- 추론비 상한: `$0.047616`; 추론·토큰 계산 각 최대 4회, 검색 최대 2회, 문항별 1회, 재시도 0회
- 계획·judge 호출: 각 0회
- 이번 실행 정책에만 `ALLOW_UNVERIFIED`를 명시했다. 기본값은 `REQUIRE_CONFIRMED`이며 명시적 허용이 없는 미확인 계산 비용은 계속 차단한다.
- 계산 비용·총 청구액은 `null`, 과금 확인은 `false`로 보존한다. 총 청구액 `$0.10`의 보장을 표시하지 않는다.
- 허용·차단·횟수 및 추론비 상한 검사 16개 통과(실패·오류·건너뜀 0). 실행 전 이 검사만 수행했고 실패 후 추가 검사를 실행하지 않았다.
- 애플리케이션 변경은 `OpenAiBatchBudget.java`와 `OpenAiBatchBudgetTest.java` 두 파일이며, 별도 작업 트리의 `eval/openai-strict-two-cases` 브랜치에 미커밋 상태로 보존했다.

## 문항별 결과

| 문항 | 실행 결과 | 도구 선택·인자 정확도·근거 설명 |
|---|---|---|
| `PLR-TM-palaces-01` — 창경궁을 찾아줘. | 1회 시도, `COUNT_UNAVAILABLE` | 추론·검색 이전 중단으로 평가 불가 |
| `PLR-TM-palaces-03` — 종로의 조선 왕실 가족 거처 | 미실행 | 평가 불가 |

첫 문항의 HTTP 상태는 200이지만 응답 본문의 `type=ERROR`, `termination=COUNT_UNAVAILABLE`이므로 실패로 판정했다. 서버가 반환한 안내문은 `SERVER_FALLBACK`이며 모델의 근거 설명으로 평가하지 않는다.

## 실패 원인과 보존 한계

내가 추가한 기록용 로컬 HTTP 중계기가 `Content-Length`를 기준으로 읽은 빈 본문을 JSON으로 해석하다 `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`로 실패했다. 이 오류는 OpenAI로 전달하는 코드보다 앞에서 발생했다. 요청 헤더 원문은 기록하지 않았으므로 전송 인코딩의 세부 원인은 확정하지 않는다. 중계기를 수정하거나 재실행하지 않았다.

애플리케이션에는 토큰 계산 응답 해석 실패가 기록되었으며, 추론은 `dispatched=false`다. 원래 문항, 요청 해시, 앱 요청·응답, 실행 이벤트, 예약 원장, 실행 설정, 가드 검사 XML과 기존 로그를 보존했다. 실패한 중계기는 본문을 기록하는 단계에도 도달하지 못했으므로 해당 계산 요청의 HTTP 본문 원문은 없다. 앱의 원래 모델 요청은 이벤트에 SHA-256과 UTF-8 바이트 수만 남아 있다. 없는 원문을 복원하거나 원본으로 표시하지 않는다.

## 실제 횟수와 시간

| 항목 | 횟수/시간 |
|---|---:|
| 로컬 앱 문항 요청 | 1회 |
| 로컬 토큰 계산 시도 | 1회 |
| OpenAI 토큰 계산 API 전달 | 0회 |
| OpenAI 추론 API 전달 | 0회 |
| 검색 도구 실행 | 0회 |
| 재시도·계획·judge | 각 0회 |
| 클라이언트에서 본 문항 요청 전체 | 532.5047 ms |
| 서버 API 처리 | 470.4124 ms |
| 모델 호출 가드 단계 전체 | 78.1934 ms |
| 실패한 로컬 토큰 계산 단계 | 72.6785 ms |
| 추론·검색 시간 | `null` — 미실행 |

위 시간은 서로 포함되는 구간이며 합산하지 않는다. 실제 모델 토큰 사용량은 제공자 호출이 없어 관측되지 않았고 `null`이다. `modelTurns=1`은 앱의 시도 횟수이며 추론 API 호출 수가 아니다.

## 비용

- 이 실행에서 OpenAI로 전달된 요청이 없어 호출 기준 추론 비용은 `$0`이다. 이는 청구서 확인 금액이나 토큰 사용량 관측값이 아니다.
- `input_count_cost_usd=null`, `total_billed_cost_usd=null`, `total_cost_bound_usd=null`, `invoice_confirmed=false`를 유지했다. 미확인 비용을 확인됨 또는 0원으로 기록하지 않았다.
- 원장의 `$0.011904`는 실패 전 확보한 1회분 추론 한도이며 실제 지출이 아니다. `HALTED_CALL_FAILURE` 상태와 함께 보존했다.

## 기존 작업 보존

PR #7의 develop 병합 커밋은 `49ddb1de91e818ad329c5b0e9eea3212216bf973`이다. 원본 83개와 백업 83개의 해시, 기존 작업 상태, 미포함 C05 두 파일을 다시 확인했다. C02·C03 등 잔여 묶음은 진행하지 않았다. C01의 156개 검사 수치는 이전 결과물이며 이번 실행에서 재실행하지 않았다.

주요 증거: `run.json`, `execution.jsonl`, `PLR-TM-palaces-01.request.json`, `PLR-TM-palaces-01.response.json`, `../inference-reservations.jsonl`, `../approved-inference-policy.json`, `../junit/TEST-com.yollo.TravelMate.OpenAiBatchBudgetTest.xml`, `verification.json`.
