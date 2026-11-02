# Qwen 실제 호출 전 정확 토큰 가드

`OllamaLlmClient.complete()`가 대화와 비동기 계획 생성 모두에서 `LlmCallGuard`를 호출한다. Qwen의 기존 UTF-8 보수적 상한 계산을 `QwenTokenCounter` → `ExactQwenProcess` → `Server/token_budget/exact_qwen_counter.py`로 교체했다. 다른 공급자로의 전환이나 보수적 계산으로의 자동 복귀는 없다.

Qwen이 선택되고 계산 명령이 설정된 경우 Spring 시작 시 메타데이터를 확인하고 Python 상주 worker를 초기화한다. 종료 시 worker와 Go 보조 프로세스·파이프를 정리한다. 다른 공급자가 선택됐거나 명령이 `[]`이면 worker를 시작하지 않는다.

각 호출에서 `/api/show`, `/api/version`, `/api/tags`를 새로 조회하고 **전체 native wire JSON 문자열**을 상주 worker로 전달한다. requestId와 sessionId가 일치하는 결과만 사용한다. 별도 셸이나 요청별 임시 파일 없이 UTF-8 JSONL 파이프로 통신한다. 계산 worker 자체는 모델 API를 호출하지 않는다.

현재 검증 프로필은 Windows AMD64, Ollama 0.40.13, qwen3:8b, GGUF gpt2/qwen2, think=false에 한정된다. manifest digest, 실제 GGUF SHA-256, Go renderer 실행 파일 SHA-256, libllama.dll SHA-256, Go template SHA-256, GGUF metadata와 특수 토큰 정책을 고정 검증한다. 실제 서버 tag가 로컬 manifest digest와 일치해야 한다. 모델 기본 system이나 다른 renderer, 이미지·미지원 입력은 거부한다.

검증된 Go renderer는 실제 Ollama `template` 패키지 v0.40.13으로 전체 프롬프트를 만든다. GGUF 어휘만 읽는 native tokenizer와 같은 어휘·merges를 사용한 tokenizers 0.22.2의 **모든 token ID**를 비교하고, native detokenization이 원래 UTF-8 바이트 전체를 복원하는지도 확인한다. context 생성·가중치 추론·샘플링은 하지 않는다. [검증 도구와 고정 소스](../../Evaluation/tools/qwen-tokenizer-check/README.md)를 참조한다.

`EXACT_LOCAL_CROSSCHECKED`는 이 로컬 계산의 품질 표시다. 서버가 보고한 `prompt_eval_count`나 실제 사용량인 `CONFIRMED_API`로 표시하지 않는다. 결과에는 wire/template/prompt/token-ID/model/library/renderer 해시를 기록하고, 가드는 요청 해시와 결과의 프로필 소속도 확인한다.

가드는 매번 전체 입력 토큰과 출력 예약량을 합산한다. 누적 도구 메시지·전체 원문·부정·조건·도구 정의·이력은 모두 입력에 포함된다. 첫 호출이 허용됐어도 다음 호출에서 다시 검사한다. 설정 context와 native context 중 작은 한도를 적용한다. 기본 context 8192, 출력 예약 1536은 변경하지 않았다. 생성 경로의 추가 LLM 호출도 같은 전략·가드를 사용한다.

## 설정

1. 검증된 Python 환경에 [requirements.txt](../../Server/token_budget/requirements.txt)의 버전이 있어야 한다.
2. 검증한 Go renderer와 Ollama DLL·GGUF·manifest를 [profile.example.json](../../Server/token_budget/profile.example.json)의 각 경로로 지정한다. 기대 해시를 임의 설정으로 바꿀 수 없다. 다른 빌드/플랫폼은 별도 검증 전까지 차단한다.
3. `ollama.exact-counter-command` 또는 `OLLAMA_EXACT_COUNTER_COMMAND`를 JSON 배열로 설정한다. 예:

```json
["C:/python/python.exe","-X","utf8","C:/TravelMate/Server/token_budget/exact_qwen_counter.py","--profile","C:/TravelMate/local/qwen-profile.json"]
```

`ollama.exact-counter-timeout-seconds`의 기본값은 90초다. 명령 기본값은 `[]`이며 설정이 없으면 `COUNT_UNAVAILABLE`로 차단한다. 파일·패키지 부재, 동일성 불일치, 프로세스 실패·시간 초과, 잘못된 출력, token-ID/바이트 불일치도 호출을 차단한다. 초과는 `CONTEXT_LIMIT`로 차단하며 원문 절단·context 증가·자동 유료 재시도를 하지 않는다.

명령 설정이 JSON 배열이 아니거나 timeout이 양수가 아니면 애플리케이션 시작 단계에서 거부한다.

파일 해시 검증·어휘와 독립 BPE 초기화는 worker 시작 시 한 번 수행한다. 같은 토크나이저와 Go renderer 프로세스를 재사용하지만, 입력은 누적 도구 결과까지 매번 전체를 새로 토큰화하고 token-ID·원문 바이트를 대조한다. 토큰 수 캐시는 사용하지 않는다.

요청 전후에는 모델·DLL·renderer·manifest·프로필 파일의 파일 ID/크기/mtime/ctime을 확인한다. 매회 전체 파일 해시를 재계산하지 않는다. 파일 변경이나 서버 모델·템플릿·버전 불일치를 감지하면 기존 worker를 폐기하고 해당 호출을 실패시킨다. 다음 새 요청에서 새 프로세스의 해시·어휘·동일성 검증부터 다시 수행한다. 새 모델/템플릿을 자동으로 승인하지 않는다.

worker 하나가 순차 계산하고 기본 대기 슬롯은 8개, 대기 제한은 5000ms다. `ollama.exact-counter-queue-capacity`, `ollama.exact-counter-queue-timeout-millis`로 설정한다. `QUEUE_TIMEOUT`은 활성 정상 계산을 중단하지 않는다. 초기화 `STARTUP_TIMEOUT`, 계산 `CALCULATION_TIMEOUT`, 프로세스 종료·응답 ID 불일치·검증 실패는 현재 호출을 차단하고 worker를 무효화한다. 장애 전에 대기하던 요청도 `SESSION_INVALIDATED`로 실패시키며 새 worker의 응답과 섞지 않는다. 실패한 추론을 자동 재시도하지 않는다.

`initializationMs`는 세션당 초기화 시간이며 요청마다 합산하지 않는다. `calculationMs`와 Java의 `queueWaitMs`는 요청별 시간이다. Java가 설정 명령에 `--serve`를 자동 추가하므로 기존 명령 배열은 유지할 수 있다. 명령을 직접 실행한 기본 CLI는 이전 단발 검증용으로 남겨 두었다.

[상주 검증·반복 계산 측정](../../Evaluation/runs/contextual/resident-qwen-counter-v1/20261102-01/REPORT.md)을 참조한다. 서버 메타데이터 조회와 이후 추론은 원자적 연산이 아니며 실제 서버 사용량 비교·다른 플랫폼 지원은 미검증이다. 기본 설정이 없는 환경에서 가드를 해제해 실행하면 안 된다.

## B안 전용 평가 서버 설정안

아래는 **아직 적용하지 않은 설정안**이다. 운영 설정과 기본 도구 목록·루프 한도는 유지했다.

```properties
llm.provider=QWEN
ollama.model=qwen3:8b
ollama.context-tokens=8192
ollama.max-output-tokens=1536
travelmate.conversation.allowed-tools=SEARCH_PLACES
travelmate.conversation.max-model-turns=2
travelmate.conversation.max-tool-calls=1
travelmate.conversation.tool-failure-policy=STOP
```

이 설정에서는 생성·Job 도구를 등록하지 않는다. 등록되지 않은 도구, 잘못된 인자, 검색 실패는 추가 모델 호출 전에 종료한다. 복수·반복 도구 호출은 효과를 내기 전에 도구 한도로 종료한다. 정확히 네 API 요청을 순서대로 한 번씩만 보내고 재시도를 금지하면 Qwen 추론 최대 8회·검색 도구 실행 최대 4회다. 서버 전역 공유 예산이나 임의 추가 API 요청까지 제한하는 기능으로 해석하면 안 된다. 실행자는 case ID·요청 수와 첫 실패 시 배치 중단을 별도로 통제해야 한다.
