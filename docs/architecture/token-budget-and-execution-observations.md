# 모델 호출 전 토큰 예산과 실행 관측

기준: `db38be73`. 대화 루프와 비동기 계획 생성이 같은 공급자 전략과 호출 가드를 사용한다. 이 문서는 실제 모델 품질 평가의 완료를 뜻하지 않는다.

## 예산의 경계

`StrategyLlmClient`가 기존 `supports(provider)` 레지스트리에서 GPT 또는 Qwen 하나를 선택한다. 두 구현체 모두 **최종 공급자 요청을 직렬화한 뒤** `LlmCallGuard`를 거친다. 시스템 프롬프트, 사용자 입력과 대화 이력, 도구 정의, 전체 원문·조건을 담은 도구 메시지, 누적 도구 결과와 assistant 호출, OpenAI reasoning continuation이 포함된다. 출력 예약량도 컨텍스트에서 차감한다.

계산 결과는 `CONFIRMED_API`, `CONSERVATIVE_BOUND`, `ESTIMATE`로 구분한다. 추정치나 미확인 한도로는 추론하지 않는다. 글자 수를 토큰 수로 나누는 비율 계산은 사용하지 않는다. `wireUtf8Bytes`는 전송 본문의 바이트 수이며 별도 토큰 확인값이 아니다.

| 공급자 | 입력 계산 | 한도 | 호출 후 사용량 |
|---|---|---|---|
| GPT / Responses | 동일한 input·tools·text·parallel_tool_calls·model을 `/responses/input_tokens`로 확인 | 명시한 모델과 한도 설정의 모델 ID가 같아야 함. context와 최대 출력·설정 출처 필수 | 응답 usage의 input/output/reasoning/cached. 없으면 null |
| Qwen / Ollama | 알려진 Qwen3 byte BPE와 정확히 일치하는 템플릿에 한해 UTF-8 기반 보수적 **상한** | 설정 num_ctx와 `/api/show`의 native context 중 작은 값. num_predict를 출력으로 예약 | prompt_eval_count/eval_count. reasoning 사용량을 임의로 0으로 만들지 않음 |

GPT의 `max_output_tokens`에는 숨겨진 reasoning 출력도 포함된다. 따라서 실제 output 사용량에 reasoning 사용량을 다시 더하지 않는다. encrypted reasoning은 다음 요청의 native input으로 재전달되고 입력 집계 대상에 포함되지만, 원문 내용은 관측 파일에 복제하지 않는다.

검사 순서는 모델 한도 설정 → 공급자별 입력 계산 → 입력+출력 예약 검사 → 사전 관측 저장 → 추론이다. 미확인 설정, 집계 실패, 추정치, 출력/컨텍스트 초과는 추론 전에 명시적으로 실패한다. 원문 절단·자동 요약·공급자 전환·유료 재시도는 없다. 집계 요청 자체의 실패도 자동 재시도하지 않는다. 이미 실행된 검색이나 Job 접수를 취소했다고 표시하지 않는다.

## 모델 설정과 확인 수준

GPT 모델은 저장소와 점검한 허용 목록 환경 변수에서 지정되지 않았다. 새 GPT 모델을 선택하지 않았다. 다음 설정은 실제 실행 전에 담당자가 해당 모델의 공식 문서와 대조해야 한다.

- `OPENAI_MODEL`, `OPENAI_CONTEXT_TOKENS`, `OPENAI_MODEL_OUTPUT_LIMIT`
- `OPENAI_LIMITS_MODEL`: 한도를 확인한 정확한 모델 ID
- `OPENAI_LIMITS_SOURCE`: 한도 확인 문서/버전 등의 출처
- `OPENAI_MAX_OUTPUT_TOKENS`: 요청 출력 예약, 기본 1536

빈 설정의 context/output limit 기본값은 0이며 추론을 차단한다. 출처 문자열은 운영자 확인 기록이고, 서버가 임의의 GPT 모델 제원을 자동 검증했다는 뜻은 아니다. API 키를 로그에 기록하지 않는다. 토큰 집계 endpoint의 실제 접속·모델 지원 여부와 비용 정책은 이번에 확인하지 않았다.

Qwen 기본 모델은 기존 `qwen3:8b`, context 8192, 출력 예약 1536, think=false이다. `OLLAMA_CONTEXT_TOKENS`, `OLLAMA_MAX_OUTPUT_TOKENS`로 실행 예산을 지정할 수 있다. 별도 최대 생성 길이가 확인되지 않았으므로 Qwen `modelOutputLimit`은 context에서 유도한 상한이다. 공식 독립 출력 한도로 해석하면 안 된다.

로컬 GGUF 파일의 헤더만 읽어 architecture=qwen3, context_length=40960, tokenizer=gpt2/qwen2 byte BPE를 확인했다. 이는 실행 중 Ollama 서버의 모델이나 num_ctx를 확인한 결과가 아니다. 실행 시 `/api/show` 메타데이터가 일치해야 한다.

Qwen 계산기는 템플릿 SHA-256 `ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4`만 허용한다. byte BPE의 토큰 수가 렌더링 UTF-8 바이트 수를 넘지 않는 성질을 이용하고, 모든 템플릿 분기의 리터럴·메시지·도구·호출 확장을 과다 계산한다. Go JSON 이스케이프도 고려한다. 토큰화 실행 결과나 정확한 토큰 수는 아니며, 실제로 들어갈 입력을 거부할 수 있다. 미지원 템플릿·토크나이저·구조는 집계 불가로 중단한다. 템플릿 구문 제거는 예산 계산용이며 이동 의도를 판단하는 정규식이 아니다.

## 실행 기록과 비동기 호출

`ExecutionObservationFilter`는 대화·계획·Job API에서 서버 requestId를 발급한다. turnId는 기존 Idempotency-Key, conversationId는 X-Conversation-Id와 연결한다. 평가 라벨은 X-Evaluation-Case-Id/X-Evaluation-Input-Sha256으로 받고 모델 입력에 넣지 않는다. 라벨 자체는 검증을 대신하지 않는다.

로컬 `EXECUTION_OBSERVATION_DIRECTORY`(기본 `build/observations`)/execution.jsonl에 다음을 기록한다.

- API 요청 원문과 실제 본문 해시, 응답/HTTP 상태/시간
- 모델 호출 ID·공급자·모델·phase·시작/집계/추론/전체 시간, 예산과 계산 근거, 실제 dispatch 여부·실패 사유·native 종료 상태·nullable 사용량
- 검증 **전** 실제 모델 tool_calls와 인자, 실행 결과·캐시 여부·결과 ID, LLM에 넘긴 modelData
- 서버 type/data와 primaryResultId, LLM 설명/서버 영수증/실패 설명의 messageSource, 최종 종료 사유
- Job 상태 변경의 저장소 응답 확인 및 소유자 범위 조회

대화가 generate_plan을 호출하면 기존 Executor에 현재 request/turn/tool 컨텍스트를 명시적으로 복사한다. 원래 HTTP 응답이 끝나도 추가 `LlmClient.generate()`가 jobId와 부모 tool_call ID로 기록된다. 다른 요청의 Job 조회에서도 같은 jobId로 합칠 수 있다. 작업이 대기 상태라는 이유로 DRAFT 완성으로 바꾸지 않는다. 저장 성공과 실제 DRAFT 조회를 구분한다.

관측 파일에는 실제 사용자 입력·검색 원문·장소 데이터가 포함될 수 있다. 인증 헤더/API 키와 암호화 reasoning 본문은 저장하지 않는다. 단일 프로세스 append와 실패 시 중단을 구현했으며, 다중 인스턴스 병합·보존 기간·로그 회전·접근 통제 운영 정책은 별도 과제다. 프로세스 재시작을 넘는 부모 trace 복원은 없다. Job 변경 ack는 plan_before/plan_after나 실제 DB 재조회 스냅샷이 아니다.

## 기존 평가기 연결

`Evaluation/tracks/tool_call/convert_server_trace.py`는 오프라인으로 events + 명시적 bindings + 기존 export-inputs를 받아 기존 response record로 변환한다. 기존 수집기는 검색 API 전용이므로 공통 JSONL I/O와 입력 해시 규약을 재사용하고, 원래 로컬 미커밋 수집기 파일은 수정하지 않았다.

서로 다른 해시를 유지한다: 기존 export의 model_input+harness_fixtures canonical 해시, 실제 API 본문 해시, 호출별 native wire 해시. 실제 API 질문·명시한 요청 본문·conversation ID·trace 라벨·응답과 primary server artifact가 맞아야 변환한다. exported fixtures가 서버에 모두 전달됐다고 가정하지 않는다. native message judge의 입력 자료도 실제 API 입력과 실제 tool modelData를 사용한다.

```powershell
# 기존에 선택·export한 문항과 수집한 파일에 대해서만 실행. 네트워크 호출 없음.
$env:PYTHONPATH = 'Evaluation'
python -m tracks.tool_call.convert_server_trace --events <events.jsonl> --bindings <bindings.jsonl> --exported-inputs <inputs.jsonl> --mode MOCK --output <new-records.jsonl>
```

bindings 행은 `case_id`, `input_sha256`, `request_id`, `api_request`를 포함한다. live 검색 채점에는 별도 corpus/config 검증과 대응 가능한 구조화 조건도 필요하다. MOCK와 LIVE는 서버 설정으로 구분하고 혼합은 거부한다. 기존 질문·도구 계약과 서버의 현재 계약이 다르면 compatibility_gaps로 남긴다. native generate_plan/get_planning_job을 과거 create_plan으로, PLANNING_JOB/DRAFT를 PLAN 확정 결과로 바꾸지 않는다.

평가기의 native observation_coverage는 미확인 항목을 null 점수로 제외한다. MOCK, 예산 차단, 누락된 모델 기록, 미확인 검색 corpus/조건, 없는 계획 상태/경로/기억 기록은 품질 성공이 아니다. 출처 artifact의 동일성 같은 구조 검사와 검색/계획/설명 품질은 별도다. MOCK 설명은 유료 judge 대상에서 제외하고 클라이언트도 만들지 않는다. 실제 호출이 없는 사용량은 0 토큰 성공 호출로 합산하지 않는다.

현재 연결은 기록과 변환 기반이다. 실제 검색 순위·리랭커 품질·계획 조건 준수·의미적 근거 충실성의 평가 완료가 아니다. 실제 이동시간·동선 최적화·수정/확정/롤백 기능도 포함하지 않는다. 실제 평가의 모델·기존 문항 선택·반복·예산·비용은 아직 정하지 않았으며 실행 전에 별도 확정해야 한다.

## 참고

- [OpenAI 입력 토큰 집계](https://developers.openai.com/api/docs/guides/token-counting), [집계 API](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count)
- [Responses reasoning](https://developers.openai.com/api/docs/guides/reasoning)
- [Qwen3-8B 모델 카드](https://huggingface.co/Qwen/Qwen3-8B), [Ollama API 정의](https://github.com/ollama/ollama/blob/main/docs/openapi.yaml), [GGUF 형식](https://github.com/ggml-org/ggml/blob/master/docs/gguf.md)
