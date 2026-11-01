# Qwen 정확 토큰 계산 검증과 계획 없는 검색 계약

2026-11-02. 기준 `95552e7f`. **추론은 계속 보류했다.** 동일한 native 요청·동일한 Go 템플릿의 정확한 오프라인 계산 방법을 검증하고, 검색 계약을 별도로 제안했다. 기존 가드·context·원문과 생산 검색/계획 코드는 변경하지 않았다.

핵심 결과:

- 이전 초기 요청 200개: 실제 렌더링 입력 **853~933토큰**. 기존 보수적 입력 상한은 7619~8586이었다.
- 저장된 MOCK 검색 근거 누적 요청 1개: **3000토큰**, 기존 입력 상한은 16028이었다.
- 201개 모두 이전 native 요청 해시·템플릿 해시가 일치하고, native와 독립 BPE의 **모든 토큰 ID가 일치**했다. 디코딩하면 렌더링 프롬프트의 전체 바이트가 복원됐다.
- 이 값은 **EXACT_OFFLINE_CROSSCHECKED**이다. 실제 모델 추론이나 API usage 확인값이 아니다. 가드에 연결하거나 우회하지 않았다.
- 대화 검색 도구의 계획 의존성은 서비스·DTO·근거 포맷 재사용에서 생겼다. 기존 독립 검색 GET은 계획을 요구하지 않는다.

실제 모델 추론 0, query embedding/reranking 재실행 0, 유료 호출 0, 앱 검색 API 호출 0, 계획 Job/저장/운영 DB 반영/배포 0이다. 현재 Ollama에는 메타데이터 4개 endpoint만 읽었다.

## 1. 동일성부터 확인

이전 보고서의 `initial-wire-example.json`과 각 문항의 query/history로 200개 native 요청을 재구성했다. **이전 qwen-budgets.jsonl의 wire_sha256과 200개 전부 일치해야 다음 단계로 진행한다.** 원래 API 요청의 검색 조건이 빠져 있다는 과거 한계를 고치거나 몰래 새 조건을 넣은 것이 아니다. 이전과 같은 API projection의 정확한 크기를 비교한 것이다.

저장된 도구 결과 1개는 실제 이전 MOCK events의 modelData와 호출 인자로 재구성했다. JVM Map.of의 JSON 키 순서는 이전 byte hash와 일치하는 순서를 확인했으며, 일치하지 않는 대체 입력으로 계산하지 않는다. 이 요청도 이전 해시 `73e8ac48a1b0bde596f45a417ac10d9404871b4891b7bfb624349d3245c38d3a`와 일치했다.

현재 서버 메타데이터도 다시 확인했다. Ollama 0.40.13, qwen3:8b digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, template_source=go_template와 기존 template SHA-256 `ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4`가 같았다. /api/ps는 빈 models였다. 모델을 로드하도록 API를 호출하지 않았다. [현재 메타데이터](current-qwen-metadata.json).

로컬 ollama.exe의 Go build info는 module v0.40.13, Go 1.26.10, vcs revision `04088e7c9d41cba5d33bafbf788d87a465c79d5b`·modified=false였다. 모델 GGUF 파일 전체 SHA-256도 레이어 digest `a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f`와 일치했다. 파일 해시를 위한 디스크 읽기와 모델 가중치를 계산에 적재하는 것은 구분한다. [도구체인·native 신원](toolchain-and-native-identity.json).

## 2. 정확 계산 경로

### 실제 Ollama 렌더러

임의의 Python/Jinja 템플릿이나 원문 문자열 길이로 셈하지 않았다. 설치 버전과 같은 `github.com/ollama/ollama/api` 및 `template@v0.40.13`을 import하는 작은 Go 실행 파일을 만들었다. 해당 버전의 API 타입으로 요청을 읽고 실제 Template.Execute를 실행한다.

이 경로는 system 수집, 같은 역할의 연속 메시지 병합, 개별 tool 메시지 보존, Go JSON 도구 정의/인자 변환, think=false의 /no_think와 generation suffix를 처리한다. API JSON의 바이트 수와 모델에 실제 제시되는 렌더링 문자열의 토큰 수는 다르다. 원문/부정/조건이나 메시지를 자체 요약·절단하지 않는다. 이미지, 다른 renderer, think=true/미지정은 이 검증기에서 명시적으로 거부한다.

공식 [Ollama template 구현](https://github.com/ollama/ollama/blob/v0.40.13/template/template.go), [server prompt 경로](https://github.com/ollama/ollama/blob/v0.40.13/server/prompt.go)를 대조했다. 서버의 context 절단 휴리스틱은 실행하지 않고 **전체 동일 입력**을 렌더링했다. 이 자료에서는 정확 입력+출력 예약이 모두 8192 이내이지만, 실제 서버가 어떤 처리를 했다는 관측으로 바꾸지 않는다.

Go가 로컬에 없어 공식 배포판의 SHA-256을 확인한 뒤 임시 build 폴더에만 풀었다. 전역 도구 설치나 앱 실행 설정 변경은 없다. Go module 버전과 go.sum을 남겼다.

### 같은 native 어휘 + 독립 BPE 교차 확인

설치된 Ollama의 libllama.dll을 사용했다. ABI는 Ollama 0.40.13의 LLAMA_CPP_VERSION이 지정하는 **llama.cpp b11963**과 맞췄고 DLL SHA-256을 고정했다. `vocab_only=true`, GPU layer=0으로 어휘만 읽었다. 399개 모델 텐서는 적재하지 않았고 llama context·decode·샘플링·추론은 만들거나 호출하지 않았다. [native 로그](token-counts/native-vocabulary-load.txt)에 `vocab only - skipping tensors`가 남았다.

GGUF의 151936개 어휘와 151387개 merge, Qwen2 pre-tokenizer 규칙을 별도 Rust tokenizers 구현에도 적용했다. native 로더가 보정한 특수 토큰까지 같은 정책으로 반영했다. 자동 BOS/EOS 추가는 모두 false였다. 각 프롬프트에 대해:

Ollama runner의 tokenize 요청과 고정 버전 native server의 기본값을 대조해 **add_special=false, parse_special=true**를 사용했다. [native tokenize endpoint 구현](https://github.com/ggml-org/llama.cpp/blob/b11963/tools/server/server-context.cpp). 실제 HTTP endpoint를 호출한 것은 아니다.

1. 설치 native llama_tokenize로 전체 token ID를 계산한다.
2. 독립 BPE의 전체 ID 배열과 동일한지 확인한다.
3. native detokenize가 원래 프롬프트의 모든 UTF-8 바이트를 복원하는지 확인한다.

셋 중 하나라도 다르면 실패하며 정확 계산 성공으로 기록하지 않는다. 단순한 개수 일치나 글자 수 환산 검사가 아니다. 렌더링 프롬프트·토큰 ID 해시를 [문항별 counts](token-counts/counts.jsonl)에 기록했다.

첫 렌더링 프롬프트의 끝 개행과 native 로그의 공백도 원본 그대로 보존했다. 이 두 원시 산출물만 whitespace 검사 예외로 표시했으며 프롬프트를 trim해서 해시나 토큰 수를 바꾸지 않았다.

[Ollama runner tokenize](https://github.com/ollama/ollama/blob/v0.40.13/llm/llama_server.go), [native API 헤더](https://github.com/ggml-org/llama.cpp/blob/b11963/include/llama.h), [Qwen2 tokenizer 규칙](https://github.com/ggml-org/llama.cpp/blob/b11963/src/llama-vocab.cpp). `/api/generate`를 num_predict=0으로 호출하는 식의 우회 실측은 하지 않았다.

## 3. 상한과의 차이

| 같은 요청 범위 | 이전 입력 상한 | 정확한 오프라인 입력 | 출력 예약을 포함한 정확 크기 | 현재 context |
|---|---:|---:|---:|---:|
| 초기 200개 | 7619~8586 | **853~933** | **2389~2469** | 8192 유지 |
| 저장된 MOCK 근거 후속 1개 | 16028 | **3000** | **4536** | 8192 유지 |

초기 요청에서 상한과 정확 입력의 차이는 문항별 6766~7677토큰, 저장된 후속 요청에서는 13028토큰이었다. 이전의 EXCEEDED는 **보수적 상한에 의한 거부**였고 실제 토큰 초과가 아니었다. 모든 템플릿 분기의 바이트를 여러 번 더하는 방식의 과대 계산이 확인됐다.

**숫자로는 201개 모두 들어가지만 런타임 가드는 그대로다.** 동일한 기존 상한 정책이라면 이 요청들을 계속 거부한다. 가드를 해제하거나 count quality를 API 확인값으로 위장하지 않았다. context 증가·도구 삭제·원문 절단·자동 요약·모델 전환도 하지 않았다. [전체 집계](token-counts/summary.json).

이 결과의 정확성 범위는 검증한 모델 파일·DLL·Ollama Go 버전·템플릿·think=false의 텍스트 입력이다. 실제 서버 prompt_eval_count/usage·추론 latency·응답 품질은 **미관측**이다. 아직 없는 미래 도구 결과와 비동기 generate_plan 입력의 전체 예산도 여전히 미확인이다. 새 검색 계약의 tool schema를 추가하면 그 새 native 요청을 다시 렌더링·계산해야 하며 이 숫자를 그대로 재사용할 수 없다.

## 4. 계획 없는 검색 계약

[계약 제안서](../../../../../docs/architecture/plan-independent-place-search-contract.md)에 현재 호출 경로, 필드별 차이, 입력/근거 포맷/평가 어댑터 제안을 기록했다. **새 서버 API나 도구를 구현한 것은 아니다.**

현재 대화 도구는 `SearchPlacesTool → ContextPlanningService.search → ContextPlanPromptFactory.prepare`를 재사용하므로 planningRequest와 전체 PlanContext를 요구한다. 이것은 검색의 본질적인 필수 조건이 아니다. 기존 **GET /api/places/search**는 이미 계획 없이 region/city/category 검색을 한다.

제안은 독립 PlaceSearchCriteria와 선택적 searchContext, area/exclusions를 위한 POST DTO, 공통 원문 근거 assembler이다. 시작/종료 시각·출발지·교통수단·필수 방문지·카페 최소 개수·운영시간 정책을 장소 검색에 요구하지 않는다. 가짜 계획으로 채우지도 않는다. 명시한 검색 범위는 서버 조건과 충돌 시 거부하고 제외 ID는 보존한다.

기존 검색 골든셋 **85개 전부**를 원래 입력 해시와 함께 [search-case-mapping.jsonl](search-case-mapping.jsonl)에 대응시켰다.

| 조건 | 값이 있는 문항 | 현재 독립 GET | 현재 대화 검색 도구 | 제안 |
|---|---:|---|---|---|
| region | 85 | 전달 가능 | planning 검색에서 null 전달 | 직접 필터 |
| city | 27 | 전달 가능 | null 전달 | 직접 필터 |
| category | 0 | 전달 가능 | null 전달 | 지원 유지, 현재 데이터로 실제 품질 검증했다고 주장 불가 |
| exclude_place_ids | 19 | 입력 없음 | Spring Kafka는 항상 빈 배열 | Python의 기존 제외 SQL까지 연결 |
| area | 1 | 입력 없음 | 전체 계획의 CIRCLE 필요 | 독립 원 범위 |
| history/conversation | 20 | 이력 입력 아님 | 대화 history 가능 | 원래 이력을 한 번 전달 |

지역·도시·카테고리의 필터 운반만 보면 **65개**는 기존 GET으로 표현할 수 있다. 나머지 **20개**는 제외 ID 19개/반경 1개의 입력 연결이 필요하다. 65개가 검색 품질 평가를 통과했다는 뜻은 아니다. corpus·ID·질문/조건·원문·순위·리랭커 설정 일치부터 확인해야 한다. 전체 동결 case의 persona/fixture가 모두 현재 API에 연결됐다는 주장도 하지 않는다.

제안 schema는 85개 요청을 계획 없이 표현하고 오프라인 검사를 통과했다. 현재 code adapter는 미구현이다. 기존 동결 도구 schema와 현재/제안 limit/category 필드는 차이가 있으므로 raw tool_calls를 지우거나 이름을 바꿔 구 채점기를 통과시키지 않는다. 버전별 명시적 projection과 실제 effective filters 기록이 필요하다.

현재 반경 SQL은 Haversine 직선 거리다. PostGIS로 이미 구현됐다고 바꾸거나 도보 이동시간으로 해석하지 않았다. 후보·활성 근거 상한도 그대로다.

## 5. 실제 실행 범위 재제안 — 여전히 미승인

이전 잡담 2건 제안은 검색·계획 평가의 완료 기준에서 제외했다. [새 실행 제안](execution-scope-proposal.json)은 다음 두 단계이며 **이번에는 어느 단계도 실행하지 않았다.**

### A. 기존 독립 검색 경로

- 기존 development: **PLR-TM-palaces-01**, **PLR-TM-palaces-03**.
- 지역/도시 필터를 기존 GET으로 운반하고 SEMANTIC_ONLY·RERANKED를 각각 1회 비교하는 안. **검색 요청 최대 4회**, 대화/계획 LLM·judge 0회.
- 검색 내부 embedding/reranker의 실제 호출·배치·지연·비용은 승인 후 기록할 대상이며 0으로 가정하지 않는다.
- 평가 전용 서버/DB와 동결 corpus·ID·조건·설정 일치가 먼저다. 검색 요청은 Kafka/outbox 기록을 저장하므로 운영 DB에 보내는 단순 읽기 요청처럼 취급하지 않는다.
- 이 단계는 검색 순위·필터 평가이며 도구 선택·근거 설명·계획 품질 평가가 아니다.

### B. 계획 없이 검색하는 대화 도구

- 기존 development: 위 2개 + **PLR-TM-palaces-04**(제외/이력), **PLR-TM-family_parks-04**(500m 원/이력).
- Qwen qwen3:8b, 각 1회, 동시성 1. 문항당 도구 선택 1회 + 근거 설명 1회 안으로 **대화 추론 최대 8회**, 검색 도구 실행 최대 4회. 계획 Job/계획 LLM/judge 0회.
- 현재는 검색 계약 미구현·런타임 가드 미변경·새 도구 schema의 예산 미확인으로 차단돼 있다. 같은 fail-closed 가드 안에서 정확 계산을 연결하는 작업과 새 계약/평가 projection은 별도 승인·구현·회귀 대상이다. 가드 해제는 제안하지 않는다.
- 예상 밖/반복/여러 tool_calls는 실행 전에 중단하고, 두 번째 답변 뒤 추가 호출하지 않는 수집 경계와 전체 호출 상한을 먼저 모의 검증해야 한다. 현재 앱의 기본 6회 루프를 이 제안의 2회 상한처럼 쓰면 안 된다.
- 실제 선택된 원문을 뒷받침하는 설명과 실제 도구 인자/결과를 관측한 범위만 판정한다. 현재 없는 모델 응답을 성공으로 집계하지 않는다.

현재 승인된 실제 추론·검색 요청은 **각 0회**다. 앱 GPT 모델은 미선택, 유료 judge도 제외한다. 토큰 개수에서 지연이나 비용을 실측한 것처럼 유추하지 않았다. 위 범위를 확인한 뒤 실제 실행 허용 여부를 다시 결정해야 한다.

### 계획 평가에 남는 것

기존 DRAFT 공통 검증(체류시간 합·카페 최소 개수·필수 장소·중복·범위)은 유지한다. 실제 도로 이동시간·동선 최적화·운영시간·고정 시각·방문 비용·확정/수정/롤백·before/after 관측과 동결 PLAN preview/applied 계약은 이번에 구현하지 않았다. Job→DRAFT를 PLAN으로 억지 변환하지 않는다. 계획 실제 평가 제안 문항과 호출 수는 이번 범위에서 **0**이다.

## 검증·재현·보존

신규 Python 회귀 **10개 통과**, Go 렌더러 회귀 **3개 통과**. 별도로 동일 native 입력 201개의 token ID 교차 비교와 바이트 roundtrip이 모두 통과했다. 모델 정답 채점 201건이 아니다. [모의 검사 기록](tests.json), [도구 사용법](../../../../tools/qwen-tokenizer-check/README.md), [보존/검증 해시](verification.json).

생산 가드·모델/context 설정·도구 루프·검색/리랭킹/거리/상한·계획 저장/검증·동결 골든셋·이전 보고서·원래 로컬 미커밋 수집기는 변경하지 않았다. 별도 오프라인 검증기와 계약 제안/모의 투영만 추가했다.
