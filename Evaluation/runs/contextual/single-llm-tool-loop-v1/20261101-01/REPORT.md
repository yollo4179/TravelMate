# 단일 LLM 도구 루프·GPT/Qwen 전략 모의 회귀

2026-11-01. 기준 커밋 `2756ff127f7aacba48ddbe5bd89422da680aa9a8`.
[구조·도구 계약·설정·한계](../../../../../../docs/architecture/single-llm-tool-loop.md).
이번 범위는 기존 검색·비동기 계획 생성 서비스를 호출하는 대화 루프와 공급자 전략이다.
실제 모델·검색·운영 DB·배포를 실행하지 않았다.

## 구현한 경로

기존 LlmClient는 generate(system, user)만 제공했고 Ollama Qwen만 구현돼 있었다.
이번에는 chat(messages, tools) 계약과 native 도구 응답 변환을 추가하고 기존 generate를 보존했다.

| 대상 | 구현 |
|---|---|
| 모델 전략 | LlmStrategy.supports와 주입 목록으로 QWEN 또는 OPENAI 전략 하나만 선택. 기존 소비자는 @Primary StrategyLlmClient 재사용 |
| Qwen | 기존 Ollama chat 경로/모델/생성 옵션 유지. tools·assistant 호출·tool_name 결과 메시지 변환 |
| GPT | OpenAI Responses API의 function_call/call_id/function_call_output. stateless reasoning continuation을 턴 내 재전달 |
| 모델 설정 | 기본 QWEN 유지. GPT 모델명·키는 환경설정 필수이며 모델을 임의 선택하거나 자동 유료 fallback하지 않음 |
| 대화 API | 인증 필요 경로 POST /api/v1/conversation/turns. message, 기존 planningRequest, USER/ASSISTANT 텍스트 이력 |
| 실행 도구 | search_places, generate_plan, get_planning_job만 등록 |
| 반복/실패 | 호출 이력·결과 누적, 실패 결과 전달, 중복 실행 캐시, 호출 ID 검사, 설정 가능한 모델/도구 한도, 자동 재시도 없음 |
| 응답 소유권 | type/data는 실제 서버 결과. 모델은 message/citations만 작성. 모델이 type/data를 출력하면 설명 거부 |

운영 도구 반복·시간·토큰 한도는 합의·측정 완료 상태가 아니다.
개발 기본 한도는 모델 6회·도구 8회이며 이번에는 모의 테스트에서만 실행했다.
한도는 토큰 예산이나 응답 지연의 검증값이 아니다.

## Job 접수·DRAFT 완성 구분

generate_plan은 빈 객체 인자를 받고 전송된 GeneratePlanRequest로 기존 생성 작업을 요청한다.
같은 사용자·턴 키에서 생성 키를 서버가 결정하고 기존 작업 저장소의 idempotency 검사를 재사용한다.
QUEUED/RUNNING은 PLANNING_JOB이며 완료된 일정으로 표시하지 않는다.
FAILED 역시 실패 작업 영수증이다. 이 세 상태의 설명은 서버가 작성하여 모델의 완료 표현을 그대로 노출하지 않는다.
SUCCEEDED와 planId만으로 끝내지 않고 실제 본인 DRAFT를 조회하고 ID를 대조한 뒤 DRAFT를 반환한다.

get_planning_job은 사용자 소유권이 적용되는 기존 조회를 사용한다.
한 턴 안에서 같은 작업의 반복 조회는 캐시하고 대기/sleep/polling 루프를 돌리지 않는다.
다른 턴에서 다시 조회해야 이후 완료 상태를 확인할 수 있다.
모델이 생성 이후 추가 검색을 해도 서버의 주 결과 우선순위로 Job 영수증/DRAFT를 보존한다.

이 도구는 평가 설계의 preview create_plan과 동일한 계약이 아니다.
현재 없는 modify_plan·확정·롤백은 등록하지 않았다. 실제 이동시간·최적 동선·방문 시각 계산도 추가하지 않았다.

## 검색 원문·서버 데이터 보존

공개 검색 데이터는 기존 PlaceSearchResponseDto를 사용한다.
모델에는 기존 ContextPlanPromptFactory의 구조화 근거를 재사용하여 original/annotations/generatedSupplement/retrieval을 구분해 전달한다.
원문·출처·귀속·관계·조건·부정/과거/상충 기록을 전달하며 400자 설명만으로 대체하지 않는다.
여러 검색의 근거 ID가 충돌하지 않도록 실행별 서버 범위를 붙인다.
최종 인용의 placeId·evidenceId·sourceId·정확한 quote는 실제 전달한 근거에서만 허용한다.
계획 생성의 기존 공통 DRAFT 검증과 인용 소속 검사도 유지한다.

인용 검사는 출처 소속과 허용 문자열 검사다. 올바른 원문을 잘못 해석한 설명,
인용 없이 만든 사실, 부정 반전·상충 무시를 의미적으로 검증했다고 보지 않는다.
이동 정규식이나 별도 판정 LLM을 추가하지 않았다.

## 실행과 결과

Server/TravelMate에서 다음 지정 모의 회귀만 오프라인 실행했다.

```powershell
.\gradlew.bat --offline test `
  --tests com.yollo.TravelMate.LlmStrategyTest `
  --tests com.yollo.TravelMate.ConversationToolLoopTest `
  --tests com.yollo.TravelMate.ConversationControllerTest `
  --tests com.yollo.TravelMate.DraftPlanValidationTest `
  --tests com.yollo.TravelMate.SearchEvidencePipelineTest `
  --tests com.yollo.TravelMate.ContextPlanPipelineTest `
  --tests com.yollo.TravelMate.PlanContextContractTest `
  --console=plain
```

| 클래스 | 통과 | 실패/오류/건너뜀 |
|---|---:|---:|
| LlmStrategyTest | 11 | 0/0/0 |
| ConversationToolLoopTest | 24 | 0/0/0 |
| ConversationControllerTest | 3 | 0/0/0 |
| DraftPlanValidationTest | 18 | 0/0/0 |
| SearchEvidencePipelineTest | 7 | 0/0/0 |
| ContextPlanPipelineTest | 2 | 0/0/0 |
| PlanContextContractTest | 2 | 0/0/0 |
| 합계 | **67** | **0/0/0** |

파라미터화 개별 실행을 포함한 JUnit 수다. 실제 여행 질문의 평가 문항 수가 아니다.
[JUnit 결과](junit/)와 [검증 집계·파일 해시](verification.json)를 공개한다.
공개 파일과 비교할 수 있게 줄바꿈/소스 해시는 UTF-8/LF로 정규화한다.

### 확인한 것

- Spring에서 두 전략 중 하나가 @Primary LlmClient로 선택됨. 누락/중복 전략은 실패하고 다른 공급자에 fallback하지 않음.
- MockRestServiceServer에서 GPT call_id/arguments 문자열·reasoning 재전달과 Qwen arguments 객체·tool_name·기존 JSON 생성 옵션 확인.
- 실제 공통 루프가 검색 도구를 선택한 모의 LLM 호출을 실행하고, assistant/tool 메시지와 전체 근거를 다음 호출로 전달함.
- 공개 장소·계획 데이터는 서버 결과와 일치. 모델이 최종 type/data를 만들면 거부하며 이미 얻은 데이터는 보존함.
- 다른 장소 귀속·미전달 출처 ID·생성 보충 문맥·원문에 없는 긍정형 인용을 거부함.
- QUEUED/RUNNING/FAILED를 모델의 완성 표현으로 바꾸지 않음. SUCCEEDED인 본인 작업에서 실제 DRAFT를 읽음.
- 중복 생성은 턴 내 1회 실행하고, 요청 재전송의 생성 키는 동일함.
- 후속 검색이 생성 영수증을 덮지 않음. 한도 도달·모델 실패 이후에도 실제 결과를 보존함.
- 미구현 수정/롤백·잘못된/추가 인자·중복 호출 ID·다른 사용자 작업 조회 실패를 처리함.
- 기존 초안 공통 검증 18개와 원문 전달 7개 등 기존 지정 회귀가 통과함.

### 이 검증이 대신하지 않는 것

서비스/도구 실행은 실제 Java 코드지만 외부 경계는 Mockito/MockRestServiceServer다.
컨트롤러 검사는 standalone MockMvc로 입력 계약과 기존 인증 principal 전달을 확인했다.
실제 JWT 필터/운영 보안·네트워크·Kafka·DB·비동기 Job 완료 전체를 통합 실행하지 않았다.
기존 SpringBootTest 중 실제 모델/DB를 호출하는 테스트는 실행하지 않았다.

## 남은 항목과 다음 실제 실행 전 조건

1. **토큰 예산 미해결.** 실제 GPT/Qwen 모델·버전·도구 지원, context/출력 한도와 전체 원문+도구 정의+대화/도구 이력+reasoning+출력 예약량을 확인해야 한다. 기존 Qwen 8192/1536이나 새 GPT 출력 설정을 안전한 예산으로 판정하지 않았다.
2. 실제 호출 전에는 기존 데이터셋/트랙·case ID·모델/반복·호출 횟수·비용을 먼저 확정해야 한다. 대화 호출 외에 기존 비동기 생성 LLM 호출이 추가될 수 있다. 이번에는 새 품질 평가 범위나 질문을 만들지 않았다.
3. 도구 선택 정확도, 넓은 검색/리랭킹 품질, 자연어 조건 추출·준수, 설명의 의미 정확성은 별도 실제 평가다. 구조화 planningRequest의 모든 조건을 자연어에서 자동 갱신하는 기능은 구현하지 않았다.
4. 도구 호출/결과 관측은 API 응답에만 있다. 실제 수집기·case_id/input_sha256·기존 평가기 어댑터 연결, 검색/계획/상태별 채점은 아직 미완료다.
5. 대화/턴 결과 영속화·프런트엔드 연결·수정/미리보기/확정/롤백은 미구현이다. Idempotency-Key가 전체 대화/검색/모델 호출까지 정확히 한 번만 실행하도록 보장하는 것은 아니다.

실제 모델 호출 **0**, 실제 검색 실행 **0**, 운영 DB 반영 **0**, 배포 **0**.
기본 작업공간의 미커밋 수집기·검색 평가 확장은 복사/수정/실행하지 않았다.
검색 코드·순위·기존 거리·활성 20/후보 30·DRAFT 검증/저장 정책은 유지했다.

API 형식 참고는 [OpenAI 공식 함수 호출](https://developers.openai.com/api/docs/guides/function-calling),
[reasoning 이력 보존](https://developers.openai.com/api/docs/guides/reasoning),
[Ollama 공식 도구 호출](https://docs.ollama.com/capabilities/tool-calling)이다.
