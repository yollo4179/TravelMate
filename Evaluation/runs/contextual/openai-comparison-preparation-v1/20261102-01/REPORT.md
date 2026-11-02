# OpenAI 앱 모델 비교 준비

기준 코드 `cea99c43`. Qwen 추가 재시험을 보류하고 기존 `OpenAiLlmClient` Responses API 전략의 연결을 모의 검증했다. 실제 API·토큰 계산 API·Qwen·검색·임베딩·리랭킹 호출은 모두 0회다. 서버 교체·DB 반영·배포도 하지 않았다. 이 보고서는 실제 모델 품질 평가 결과가 아니다.

## 모델 권장안과 공식 확인

앱 비교 후보는 **`gpt-5.4-mini-2026-03-17`**이다. 비용과 지연을 고려하는 첫 도구 호출 진단에 적합하다는 제안이며, 이 앱에서 Qwen보다 잘한다는 실측 결론은 아니다. 평가용 judge 모델은 선택하지 않았고 실행 범위에도 없다. 현재 앱 기본 공급자와 실행 중인 Qwen 설정은 유지했다.

2026-11-02 확인한 [공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.4-mini)는 해당 snapshot, Responses API, function calling, Structured Outputs 지원을 명시한다. 문서상 context는 400,000, 최대 출력은 128,000 tokens, 기본 reasoning effort는 none이다. 가격은 100만 tokens당 입력 **$0.75**, 캐시 입력 **$0.075**, 출력 **$4.50**이다. 이번 제안은 표준 처리·비지역 엔드포인트·텍스트 입력을 전제로 하며 캐시 할인은 계산에 사용하지 않는다.

이 모델은 최신 모델이라는 이유로 고른 것이 아니다. 버전을 고정할 수 있고 기존 API 전략을 그대로 쓰는 저비용 비교 후보로 제안한다. 계정의 해당 모델 접근 권한은 확인하지 않았으며 키나 모델 목록 API를 조회하지 않았다. 실제 도구 선택과 한국어 근거 설명 품질·지연은 미측정이다.

## 현재 구현과 변경

| 항목 | 확인 또는 변경 |
|---|---|
| 전략 선택 | 기존 `StrategyLlmClient`의 OPENAI 구현 재사용. 다른 공급자 자동 fallback 없음 |
| 요청/도구 경계 | 대화 system 및 도구 설명에 요청 봉투를 arguments로 복사하지 않도록 명시 |
| 검색 스키마 | `place-search-v2` 유지. query 필수, 선택 필터·기본값 및 추가 필드 금지 유지 |
| 서버 검증 | 변경 없음. 잘못된 필드 자동 삭제·검색어 추측·실패 재시도 없음 |
| 처리 등급 | OpenAI 요청에 `service_tier=default` 명시. 프로젝트 auto 설정에 따라 처리 등급이 달라지는 것을 방지 |
| 토큰 가드 | 매 호출의 전체 native input을 `/responses/input_tokens`로 확인한 후 입력+출력 예약량 검사. 원문 절단·context 증가 없음 |
| 실제 런타임 | 모델·키·실행 공급자 설정 및 서버 프로세스 변경 없음 |

`service_tier=default`가 표준 처리라는 의미는 [Responses API 참조](https://developers.openai.com/api/reference/python/resources/responses)에 근거한다. 이는 계정의 사용 가능 등급이나 청구 내역을 확인했다는 뜻이 아니다.

사용자 요청 예:

```json
{"message":"창경궁을 찾아줘.","searchContext":{"region":"서울"}}
```

검색 도구 arguments 예:

```json
{"query":"창경궁","region":"서울"}
```

선택 필터를 생략하면 서버가 요청의 `searchContext`를 상속한다. `searchContext` 자체, `message`, `planningRequest`를 검색 arguments에 넣지 않는다. query는 모델이 직접 작성해야 한다. 요청의 camelCase `excludePlaceIds`와 도구의 snake_case `exclude_place_ids`도 구분한다.

### 구조화 도구 호출의 실제 적용 범위

현재 검색 도구는 Qwen과 같은 canonical parameters를 전달하고 OpenAI에 **`strict=false`**를 명시한다. 서버 JSON 스키마의 `additionalProperties=false`와 공급자 단계에서 스키마를 강제하는 것은 다르다. 현 설정에서 API가 추가 필드를 반드시 차단한다고 주장할 수 없다. 최종 설명도 현재 prompt의 JSON 계약과 서버 parser로 검증하며, API의 엄격한 최종 응답 스키마는 설정하지 않았다.

[공식 function calling 문서](https://developers.openai.com/api/docs/guides/function-calling)에 따르면 strict=true는 각 객체의 additionalProperties=false 및 모든 properties의 required 지정을 요구한다. 선택 필드는 nullable로 표현할 수 있다. 현재 검색 계약은 query만 필수이고 limit은 생략 시 10, 명시 null은 거부한다. 그대로 strict=true만 붙이면 호환되지 않는다.

따라서 첫 제안은 같은 canonical 계약과 서버 검증을 유지하는 비교다. nullable 선택 필드를 모두 required로 만드는 strict 변형은 별도 변경·평가로 다뤄야 한다. 이번에는 구현·등록·실행하지 않았다. API 지원 기능만으로 이번 인자 오류가 해결됐다고 표시하지 않는다.

경계 안내를 이번에 보강했으므로 과거 Qwen 기록과 system/tool 설명 문구는 완전히 동일하지 않다. 실제 API 결과가 좋아져도 모델 하나의 효과로 단정할 수 없다. 이를 맞추기 위해 Qwen을 추가 호출하지 않았다.

## 기존 2문항 실행 제안 — 미승인·미실행

원본 범위는 `search-tool-contract-output-v1/20261102-01/next-execution-proposal.json`에서 읽었다. [proposal.json](proposal.json)에 그 파일 해시와 API 요청·case_id·입력 해시를 그대로 보존했다. 골든셋과 기존 실행 기록은 변경하지 않았다.

| case_id | 입력 SHA-256 | 요청 |
|---|---|---|
| PLR-TM-palaces-01 | `13f07e1370f08c3962a159bbf18ff3ef60b7a5b2d03f1d550a34c96f70f9598b` | 창경궁을 찾아줘. |
| PLR-TM-palaces-03 | `42a6a1b0fb5c40e8be6c37f1cf5e685c982b4d927151646eb6b2467478d8246d` | 종로에서 조선 왕실 가족이 생활했던 궁이나 거처를 둘러보고 싶어. |

- 각 1회·순차·재시도 0. 요청당 모델 턴 2·도구 1·실패 시 STOP.
- 추론 dispatch 최대 **4회**. 실패한 dispatch도 상한에 포함.
- 별도로 입력 토큰 계산 API 최대 **4회**. 이를 포함하면 OpenAI HTTP 요청 최대 **8회**이며, 추론 8회를 뜻하지 않는다.
- 검색 백엔드 최대 **2회**. Qwen·계획·judge·새 임베딩 0회.
- 로컬 입력+출력 한도 **8192**, 출력 예약 **1536**, 호출별 입력 최대 **6656 tokens**. 모델 고유 context 한도와 구분한다.
- 첫 도구/서버/응답/인용 오류, 예산 초과, 기록 실패, 자료·설정 불일치에서 중단. timeout은 결과 미확인으로 보존하고 재전송하지 않는다.

### 비용

캐시 할인을 제외한 추론 token 비용의 계산 상한:

```text
입력: 4 × 6656 = 26,624 tokens × $0.75 / 1,000,000 = $0.019968
출력: 4 × 1536 =  6,144 tokens × $4.50 / 1,000,000 = $0.027648
합계: $0.047616
```

이는 위 호출·토큰 상한을 실제로 지킨다는 조건의 추론비 상한이며, 예상 실제 사용량이나 계정 총 청구 상한 확인값이 아니다. 출력 예약량은 reasoning을 포함한다. 전체 system/history/tools/원문/누적 결과/재전달 reasoning도 입력 계산에 들어간다. 후속 근거로 입력이 커지면 호출 전에 실패하며 잘라서 맞추지 않는다.

**제안할 배치 지출 상한은 USD $0.10**이다. 그러나 아직 승인·설정·집행된 한도가 아니다. [공식 토큰 계산 안내](https://developers.openai.com/api/docs/guides/token-counting)에서 확인한 endpoint 동작과 별개로, 확인한 문서에는 그 endpoint의 별도 과금 여부가 명시돼 있지 않았다. 무료로 간주하지 않는다. 세금·환율도 위 식에 포함하지 않았다. 전체 최대 청구액을 확정했다고 표시하지 않으며, 실행 전 계정의 과금 조건 확인이 남는다.

## 모의 검증

JUnit **74개·실패 0·오류 0·건너뜀 0**. 아래 여섯 클래스만 선택했고 실제 DB/검색/모델 통합 검사는 실행하지 않았다. JUnit XML은 [junit](junit/)에 보존했다.

```powershell
# Server/TravelMate에서 실행하는 오프라인 모의 검사
.\gradlew.bat --offline test --tests com.yollo.TravelMate.OpenAiSearchComparisonPreparationTest --tests com.yollo.TravelMate.SearchToolContractRegressionTest --tests com.yollo.TravelMate.LlmStrategyTest --tests com.yollo.TravelMate.BudgetedProviderTest --tests com.yollo.TravelMate.ConversationToolLoopTest --tests com.yollo.TravelMate.TokenBudgetGuardTest
```

추가한 기술 회귀 두 건은 모두 기존 palaces-01의 과거 성공 기록과 최근 실패 기록을 사용한다. 새 골든 문항이 아니며, 실제 비교 대상 두 문항을 실행한 것이 아니다.

1. 성공 기록의 native arguments를 OpenAI 모의 function_call 응답으로 재생했다. 실제 OpenAI 전략·전체 입력 가드·대화 루프·모의 검색·후속 도구 결과·인용 parser를 통과한다. 원문 전체, metadata, 장소 귀속 및 생성 보충 문맥의 분리가 후속 요청에 유지된다.
2. 최근 Qwen의 `query/region/searchContext` 원본 arguments를 같은 OpenAI 모의 응답으로 재생했다. 문자열을 변경하지 않고 `Unknown tool argument: $.searchContext`로 거부, 검색 0회, 추가 모델 호출 0회로 종료했다.

성공 회귀의 설명·인용 문장은 과거 기록을 사용하고, 인용 ID는 모의 공급자가 이번 요청에 전달받은 ID로 응답한다. 이전 실행의 무작위 namespace ID를 복사해 인용하면 서버 검증에서 거부되는 것도 개발 중 확인했다. 이를 해결하려고 운영 parser를 느슨하게 하지 않았다. mock 응답·mock count(1000/2000)·mock 점수는 실측값이나 모델 정확도로 계산하지 않는다.

원본 corpus·출처·골든셋·과거 보고서 내용과 검색 스키마는 수정하지 않았다. 사용자 로컬 미커밋 수집기·평가 코드 4개도 이전 보존 해시와 일치했다. [verification.json](verification.json)에 제안 재생성·기존 입력 보존·JUnit 집계와 해시를 기록했다.

제안 생성기는 HTTP나 실행 옵션을 가지지 않는다. 아래 명령도 추론·검색 없이 새 파일만 만든다. 이미 존재하는 출력에는 덮어쓰지 않고 실패한다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/prepare_openai_comparison.py --output Server/TravelMate/build/openai-comparison-proposal.json
```

## 실제 실행 전 남은 조건

1. 사용자가 앱 모델과 지출 상한을 확정한다. judge 모델과 혼동하지 않는다.
2. 계정의 모델/표준 등급 접근 및 토큰 계산 endpoint 과금 조건을 확인한다. 이번 준비에서는 실제 API 요청이나 키 조회로 탐색하지 않았다.
3. 승인 뒤 새 OpenAI 평가 runtime에 모델·키·한도를 연결한다. 기존 Qwen runtime과 관측 파일을 덮어쓰지 않는다. 현재 `run_b.py`는 Qwen 프로필 전용이므로 그대로 OpenAI 실행에 사용하지 않는다.
4. 기존 collector에 승인된 OpenAI 모델/등급 확인, 계산 API 수, 배치 호출·비용 예약과 사용량 집계를 연결하고 모의 검사한다. 현재 구현된 per-call token guard를 배치 USD 지출 가드로 오인하지 않는다.
5. 실행 JAR·코드 해시, corpus/원문/검색 설정과 관측 저장을 다시 결속한다. 승인 전 추론·검색으로 점검하지 않는다.

실행 후 원본 tool_calls/인자와 적용 필터, 결과 순위·원문·선택 근거, 후속 LLM 입력, 설명·인용, 종료 사유 및 사용량을 보존한다. 기존 평가 변환은 원본과 구분하며 없는 관측은 성공으로 채우지 않는다. 도구 선택·인자, 검색 관련도, 근거 전달, 설명의 근거 일치를 각각 판정한다.

OpenAI 입력 계산 시간·추론 HTTP 시간·도구 실행·CPU 임베딩/리랭킹·전체 API 지연을 분리한다. 과거 CPU 리랭킹 약 112.268초는 이 준비에서 해결하지 않았고, API 모델로 바꿔도 검색 지연이 없어지는 것은 아니다. OpenAI 예상 지연은 실측 근거가 없어 수치로 만들지 않았다.

2문항 결과로 일반 검색·설명 전체 품질이나 Qwen 전체 품질을 단정하지 않는다. 원래 B안의 나머지 두 문항, 계획 조건 준수·수정·확정·롤백·이동시간·동선 최적화는 이번 범위에 없다.
