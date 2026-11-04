# LiLi 라우터 회귀 9문항 실측 (2026-11-04)

- 서버: 공통 평가 서버(B안 인프라), `LILI_ROUTER_V1`, OpenAI `gpt-5.4-mini-2026-03-17`, 검색 GPU(cuda)
- 평가기 커밋 `4aec8565`. 설정 `live.lili-regression.json`, 이어서 실행한 나머지 4문항은 `live.lili-regression-r2-rest.json`
- 기록: `Evaluation/runs/conversation-smoke/20261104-lili-r2`, `20261104-lili-r2-rest`
- 비용(캐시 할인 전 사용량 기준): 15회 호출, $0.034834. 청구서로 확인한 값은 아니다.

`20261104-lili-r1`은 러너의 HTTP 완료 계약 결함 때문에 첫 문항에서 멈춘 기록이다.
당시 계약은 단일 LLM 기준이었다(모델 턴 1회, 인용 필수, PLACES 응답). `4aec8565`에서 라우팅별 계약으로 고쳤다.
같은 case는 예산 원장에서 재시도가 막히므로 새 원장(r2)으로 서버를 다시 띄워 실행했다.

## 결과: 자동 검사 8/9

| 문항 | 기대 → LiLi 분기 | 검색어 | 자동 | 라우터(ms) | 작업 검색 / 추론 (ms) |
|---|---|---|---|---|---|
| PLR-TM-palaces-01 | SEARCH → SEARCH | 서울 창경궁 | 통과 | 2441 | 15157 / 4596 |
| PLR-TM-palaces-03 | SEARCH → SEARCH | 종로 조선 왕실 가족 관련 궁궐과 거처 | 통과 | 3479 | 22097 / 4045 |
| CONV-SOCIAL-thanks | CHAT → CHAT | – | 통과 | 2045 | – |
| CONV-CLARIFY-plan | CLARIFY → CLARIFY | – | 통과 | 2039 | – |
| CONV-CLARIFY-job | CLARIFY → **GET_PLANNING_JOB** | – | **실패** | 2267 (+후속 2068) | – |
| CONV-UNSUPPORTED-booking | CHAT → CHAT | – | 통과 | 1995 | – |
| CONV-SEARCH-exclude-first | SEARCH → SEARCH | 종로 관광지 | 통과 | 1770 | 3510 / 3063 |
| CONV-PLAN-create | PLAN → PLAN | 서울 종로 관광지 창경궁 포함 일정 | 통과 | 1778 | (계획 작업 아래) |
| CONV-JOB-owned | JOB → JOB | – | 통과 | 1933 (+후속 2069) | – |

대화 턴은 사전 검색 없이 1.8~3.5초에 LiLi 대사를 돌려줬다. 이전 단일 LLM 구조는 사전 검색만 2.6~32.7초였다.
추천 작업의 인용 5건은 모두 전달된 원문 안에 있었다(창경궁 378).

## 발견한 문제

1. **작업 ID 없는 진행 상태 질문** (`CONV-CLARIFY-job`)
   - LiLi는 CLARIFY 대신 `GET_PLANNING_JOB`을 골랐다.
   - 서버가 UUID를 찾지 못해 후속 대사로 넘어갔다.
   - 라우터 입력에는 `planningRequestProvided`만 있고, 작업 ID 유무는 없다.
2. **후속 대사가 내부 사유를 그대로 노출**
   - "서버가 JOB_ID_NOT_FOUND라고 알려줬어"
   - "LLM 호출 전 토큰 예산 검사 실패: COUNT_UNAVAILABLE"
   - 후속 프롬프트가 "서버가 준 사유를 말한다"고 지시하고, 작업의 `errorMessage` 원문을 받는다.
3. **추천 대사의 근거 밖 서술**
   - palaces-03은 근거가 없는 운현궁을 "조용하고 사적인 왕실 거처 느낌"이라고 묘사했다.
   - exclude-first는 대사에 장소 이름 4개를 나열했고, "셀렉트된 근거가 없어서"라는 내부 표현을 썼다.
   - 의미 검수 대상이다.
4. **계획 생성 실패** (`CONV-PLAN-create`의 작업 `a84720e3`)
   - 검색 26초, 생성 6초 뒤 검증에서 실패했다: "방문 체류시간이 여행 가능 시간을 초과합니다". 조건은 10:00~12:00, 창경궁 60분 필수였다.
   - 계획 생성 모델의 응답 본문이 관측 로그에 남지 않아, 어느 핀이 초과했는지 확인할 수 없다.
5. **작업 검색 지연**: 추천 작업의 검색이 3.5~22초, 계획 작업의 검색이 26초다. 이미 알려진 검색 지연 문제와 같다.

자동 통과는 경로와 형식만 판정한 것이다. 라우터 대사 사실 주장 여부(`router_line_no_place_facts`)와 답변 품질은 `review.csv`로 사람이 검수해야 한다.
