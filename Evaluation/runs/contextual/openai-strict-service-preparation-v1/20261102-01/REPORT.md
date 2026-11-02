# OpenAI strict 검색·배치 예산 준비

기준 `d26c995d`. 기존 서버 검색 계약을 유지하면서 OpenAI용 strict 스키마와 명시적인 변환·비용 통제 경로를 구현했다. 현재 설정 기본값은 CANONICAL이며, 실제 Spring 공급자·모델·키·JAR를 변경하지 않았다. 유료 호출, 토큰 계산 API 호출, 검색 재실행, judge·계획 호출은 **0회**다.

목적은 **서비스 구성의 적합성 검증 준비**다. Qwen과 동일한 공급자 설정의 모델 성능 비교로 표시하지 않는다. 별도로 적용한 [검색 GPU 구성](../../search-gpu-activation-v1/20261102-01/REPORT.md)은 실제 장치 적재만 확인했으며 검색 속도 실측은 아니다.

## strict 파이프라인

기존 `StrategyLlmClient → OpenAiLlmClient → Responses API`를 재사용한다. `openai.tool-contract-mode=STRICT_SEARCH_V1`을 명시할 때만 검색 도구에 공급자 projection을 적용한다. 전략 registry가 canonical 통과와 strict 검색 projection 중 하나를 선택한다. Qwen 전략과 서버 `SearchPlacesContract`는 변경하지 않았다.

| 구분 | 서버 canonical | OpenAI STRICT_SEARCH_V1 | 서버로 넘기는 값 |
|---|---|---|---|
| query | 필수, 빈 문자열·공백 금지 | 필수 string, null 불가 | 원값; 누락·오류면 거부, 추측하지 않음 |
| region/city/category | 선택·nullable | 필수·nullable | 원값; null이면 기존 context 상속 |
| exclude_place_ids | 선택·nullable | 필수·nullable | 원값; 기존 제외 ID union 유지 |
| area | 선택·nullable | 필수·nullable | 원값; 기존 반경·범위 검사 유지 |
| limit | 선택, 생략 시 10, 명시 null 거부 | 필수·nullable | **null만 10으로 변환**; 숫자는 원값 |
| 추가 필드 | 거부 | 모든 객체에 additionalProperties=false | 임의 삭제 없이 거부 |

[공식 function calling 문서](https://developers.openai.com/api/docs/guides/function-calling)의 strict 요구사항에 맞춰 공급자 스키마에는 모든 properties를 required로 지정했다. 중첩 area/center의 기존 required와 추가 필드 금지도 유지한다. nullable는 anyOf로 표현한다.

[공식 지원 스키마 문서](https://developers.openai.com/api/docs/guides/structured-outputs)에 명시된 부분집합을 사용하기 위해 provider projection에서는 `default`, `minLength`, `maxLength`, `uniqueItems`를 제거했다. 숫자 범위와 pattern은 유지한다. 길이·중복·기본값 등 서버 제약은 바꾸지 않았고 변환 후 canonical 검증을 다시 수행한다. 따라서 strict가 서버의 모든 조건이나 검색어 의미·관련도까지 보장한다는 주장은 하지 않는다. 실제 API의 해당 스키마 수락은 미호출 상태라 미검증이다.

strict 응답에서 필드가 누락되면 canonical에서 선택 필드여도 먼저 거부한다. 잘못된 query나 추가 searchContext를 보충·삭제해 성공시키지 않는다. 모델이 생성한 보충 문맥과 실제 원문·출처·장소 귀속·관계·조건 전달도 그대로 유지한다.

## 원본과 변환본

- `MODEL_CALL.receipt.nativeToolCalls`: 공급자의 원본 function_call, call_id, arguments.
- `TOOL_ARGUMENT_ADAPTATION`: callId, 원본 arguments 문자열, 서버 arguments 문자열, 변환 정책·성공/거부 상태.
- `MODEL_TURN.toolCalls`, 도구 실행 기록: 실제 서버 계약으로 검증하고 실행할 arguments.
- 다음 LLM 요청의 continuation: **공급자 원본 호출을 그대로 재전달**한다. null limit을 10으로 바꾼 서버 실행본으로 바꾸지 않는다.

기존 평가 변환기를 확장해 `provider_tool_calls`, `argument_adaptations`, `tool_calls_representation=server_contract`를 분리했다. 기존 `tool_calls`와 평가용 `evaluation_tool_call_projections`의 용도를 혼동하지 않는다. 실제 기록이 없으면 빈 목록이며, mock을 LIVE나 품질 성공으로 올리지 않는다. 원본 스키마와 변환 예는 `provider-schema.json`, `server-schema.json`, `mock-argument-adaptation.json`에 보존했다. mock은 문항 품질 실측이 아니다.

## 호출 전 배치 예산 연결

`OpenAiBatchBudget`를 기존 OpenAI 전략에 연결했다. strict 모드는 예산 파일 자체가 없을 때도 토큰 계산 HTTP 전에 차단한다. [unapproved-budget.json](unapproved-budget.json)은 **미승인** 상태이며 토큰 계산 단가는 null이다. 이 파일을 현재 실행 서버에 연결하거나 승인값을 변경하지 않았다.

1. 모델·context/output 설정, case_id·입력 해시·requestId 및 CONVERSATION phase를 확인한다. 계획 Job은 이 검색 전용 예산을 사용할 수 없다.
2. 토큰 계산 API 전에 호출당 입력 상한+출력 예약량의 비용과 확인된 계산 API 최대 요금을 예약한다. 최대 4회·case당 최대 2회, 같은 case의 새 requestId 재시도는 거부한다.
3. 예산 승인·계산 API 과금 확인·출처·단가가 없거나 예약으로 지출 상한을 넘으면 HTTP 전에 실패한다.
4. 파일 ledger를 CREATE_NEW로 만들고 예약을 먼저 기록한다. 기존 파일을 재사용해 서버 재시작으로 허용량을 초기화하지 못한다. 실패·timeout·미확인 결과는 예약을 돌려주지 않는다.
5. 실제 응답의 model·service_tier, 사용량을 확인한다. 사용량 누락·초과, 호출·변환 실패면 배치를 중단한다. 이후 새 요청도 차단한다. 사용량이 확인돼도 캐시 할인을 임의로 적용하거나 청구액 확인값으로 만들지 않는다.

전체 native 입력의 `/responses/input_tokens` 검사와 입력+출력 예약량 가드는 그대로다. strict 스키마·전체 원문·누적 결과·reasoning continuation도 매번 계산한다. 원문 절단, context 증가, 유료 재시도, 자동 공급자 전환은 하지 않는다. 비용 검사 때문에 실제 receipt가 사라지지 않도록 guard가 receipt를 보존한 뒤 배치 검사·strict decode를 수행한다.

## 모델·비용과 기존 실행 범위

후보는 `gpt-5.4-mini-2026-03-17`이며 아직 사용자 확정 모델이 아니다. [공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.4-mini)의 입력 $0.75/출력 $4.50 per 1M tokens, context 400,000·최대 출력 128,000을 확인했다. 로컬 평가 cap은 8192, 출력 예약 1536으로 유지한다. judge는 없다.

[proposal.json](proposal.json)은 기존 palaces-01/03의 API 요청·입력 해시를 그대로 사용한다. 새 문항을 만들지 않았다. 각 1회·순차·재시도 없음·추론 최대 4회·계산 API 최대 4회·검색 최대 2회다. 요청당 모델 2턴/도구 1회/STOP 설정은 실제 runtime 결속 때도 확인해야 한다. 현재 Qwen용 `run_b.py`를 그대로 OpenAI 실행에 사용하지 않는다.

캐시 할인을 쓰지 않은 추론비 상한은 `4 × ((6656 × $0.75 + 1536 × $4.50) / 1M) = $0.047616`다. 계산 API의 검증된 요청당 최대 요금을 C라고 하면 예약 상한은 `$0.047616 + 4C`다. 제안 예산은 여전히 **$0.10**이며, 모델·최종 예산은 미확정이다.

[공식 토큰 계산 안내](https://developers.openai.com/api/docs/guides/token-counting)와 API 문서에서 계산 endpoint의 별도 과금액을 명시한 근거를 확인하지 못했다. **무료로 가정하지 않았으며, 미확인 상태에서는 계산 API 자체도 호출하지 못하도록 연결했다.** `inputCountRequestMaxUsd=null`, billingConfirmed=false, approved=false를 그대로 남긴다. 세금·환율을 포함한 총 청구 상한이 확인됐다는 뜻이 아니다.

검토용 설정은 다음과 같다. **실행 서버에 적용한 설정이 아니다.** 실제 승인 뒤 새 runtime에 예산 파일과 새 JAR/소스/관측 경로를 결속해야 한다.

```properties
llm.provider=OPENAI
openai.model=gpt-5.4-mini-2026-03-17
openai.tool-contract-mode=STRICT_SEARCH_V1
openai.context-tokens=8192
openai.max-output-tokens=1536
openai.model-output-limit=128000
openai.limits-model=gpt-5.4-mini-2026-03-17
openai.limits-source=https://developers.openai.com/api/docs/models/gpt-5.4-mini
openai.evaluation-budget-file=<새 runtime의 승인된 예산 JSON 절대 경로>
travelmate.conversation.allowed-tools=SEARCH_PLACES
travelmate.conversation.max-model-turns=2
travelmate.conversation.max-tool-calls=1
travelmate.conversation.tool-failure-policy=STOP
```

## 검증과 남은 항목

선택한 Java 모의 회귀 **97개·실패/오류/건너뜀 0**, JAR 오프라인 빌드, 기존 평가 변환기 모의 회귀 13개, GPU 배치 전달 mock 1개가 통과했다. Java 집계와 원본 JUnit XML·JAR 해시는 `verification.json`, `junit/`에 기록했다. 새 Java 검사는 스키마·nullable/default, 원본 재전달, 누락/추가/중복/범위 오류, 예산 승인/과금/파일 누락, 비용·호출 상한, 재시도/재시작 차단, 사용량 보존과 실패 중단을 다룬다. 새 평가 문항이나 실제 모델 평가가 아니다.

API 전략에 비용 가드를 연결한 것과 실제 평가 배치를 실행한 것은 구분한다. 미승인 파일로 실제 호출을 허용하지 않았고, 기존 Spring은 이전 JAR/공급자 그대로다. 다음 실행 전 모델·최종 예산과 계산 endpoint 과금 조건 확정, 새 API runtime·관측 파일 및 기존 두 case의 결속이 남는다. 이전 Qwen runtime의 동결 manifest는 새 소스와 다르므로 재사용해 실행 가능하다고 표시하지 않는다.

실제 strict 수락, 도구 선택·검색어 의미·검색 관련도·근거 설명·인용의 의미 일치·지연은 미평가다. CPU 112초 기록을 현재 GPU 성능으로 사용하지 않는다. 다음 승인된 검색에서 임베딩/리랭킹 시간과 API 입력 계산/추론 지연을 각각 기록한다. 동일 조건 모델 우위나 전체 서비스 품질, 일정 생성·수정·확정·롤백·동선 최적화를 완료했다고 표시하지 않는다.
