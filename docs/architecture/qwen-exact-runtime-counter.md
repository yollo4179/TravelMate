# Qwen 실제 호출 전 정확 토큰 가드

`OllamaLlmClient.complete()`가 대화와 비동기 계획 생성 모두에서 `LlmCallGuard`를 호출한다. Qwen의 기존 UTF-8 보수적 상한 계산을 `QwenTokenCounter` → `ExactQwenProcess` → `Server/token_budget/exact_qwen_counter.py`로 교체했다. 다른 공급자로의 전환이나 보수적 계산으로의 자동 복귀는 없다.

각 호출에서 `/api/show`, `/api/version`, `/api/tags` 메타데이터와 **전체 native wire JSON 문자열**을 계산 프로세스로 전달한다. 별도 셸을 거치지 않고 JSON 배열로 설정한 실행 파일·인자를 사용한다. UTF-8 임시 입력은 성공·실패 시 정리한다. 계산 프로세스는 모델 API를 호출하지 않는다.

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

현재는 매 요청마다 파일 해시와 어휘를 다시 확인하므로 비용이 있다. 서버 메타데이터 조회와 이후 추론은 원자적 연산이 아니므로 실행 중 모델 tag·서버·모델 파일을 교체하지 않는 환경이 필요하다. 실제 서버 사용량과의 비교 및 다른 플랫폼 지원은 미검증이다. 기본 설정이 없는 환경에서 가드를 해제해 실행하면 안 된다.

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
