# 실제 모델 평가 직전 준비

2026-11-01. 기준 `b32486f2`. 준비·메타데이터 조사·오프라인 예산 계산·모의 검증만 수행했다. **현재 설정으로 실제 평가를 시작하면 안 된다.** Qwen 예산 상한에서 첫 호출이 차단되고 앱 GPT는 미선택이다. 이 보고서의 실행 제안은 미승인·미실행 상태다.

실제 모델 추론 0, 유료 호출 0, 검색 재실행 0, 운영 DB 반영 0, 배포 0. 로컬 Ollama에는 메타데이터 endpoint만 요청했다. 새 평가 문항·정답·모델 설정을 추가하지 않았다.

## 1. CRLF 실패를 별도 LF 체크아웃에서 확인

`git -c core.autocrlf=false worktree add --detach <별도 LF 경로> b32486f2`로 기준 커밋을 별도 체크아웃했다. 원래 작업 트리의 파일을 정규화하거나 동결 파일·manifest를 다시 생성하지 않았다.

- 이전에 실패한 `MigrationTests.test_all_archived_and_original_payload_hashes_match_before_move`를 그대로 재실행: **1개 통과**.
- 검사 대상 147개 모두 LF 체크아웃의 원시 바이트 해시가 저장된 기대 해시와 일치했다. 검사 전후 파일 해시도 같았다.
- 이전 작업 트리의 다섯 차이는 `.gitattributes` 3개와 requirements 2개의 CRLF/LF 차이였다. 기준 Git blob과 별도 LF 파일은 기대 해시와 일치한다. 내용 변경으로 분류하지 않았다.
- 같은 LF 기준 체크아웃에서 기존 평가 코드 전체 **39개 통과, 실패·오류 0**. API SDK 검사는 기존 모의 HTTP이며 실제 모델 평가가 아니다.

[보존 결과](lf-preservation.json), [원래 실패 검사 재실행 로그](lf-preservation-test.txt), [LF 전체 회귀 기록](lf-full-suite-summary.json). 이전 `b32486f2` 보고서의 실패 결과는 당시 실행 기록으로 보존했다.

## 2. 로컬 Qwen 메타데이터와 실제 예산 차단

[qwen-metadata.json](qwen-metadata.json)에 GET /api/version, /api/tags, /api/ps와 POST /api/show의 응답·시각·메타데이터 요청 지연·해시를 저장했다. /api/chat·/api/generate·모델 로드·추론 요청은 하지 않았다. 최초 탐색 4건과 보존용 수집 4건으로 실제 메타데이터 요청은 총 8건이다. Java 예산 재생의 201개 /api/show 응답은 **로컬 mock HTTP**이며 서버를 201번 호출한 것이 아니다.

| 구분 | 확인값 | 해석 |
|---|---|---|
| 서버 | Ollama 0.40.13, localhost:11434 | 메타데이터 응답 확인 |
| 설치 모델 | qwen3:8b, 8.2B, Q4_K_M | 태그 digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` |
| 템플릿 | go_template, SHA-256 `ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4` | 기존 상한 계산기의 지원 프로필과 일치 |
| 토크나이저 | gpt2/qwen2 byte BPE | 실제 토큰화 실행은 아님 |
| 로컬 모델 context metadata | 40960 | `/api/show`의 로컬 artifact 값 |
| 앱 요청 설정 | num_ctx 8192, num_predict 1536, think=false | 기준 코드·허용 목록 환경 설정 조사. 실행 중 Spring 설정을 조회한 것은 아님 |
| 실행 중 context | **미확인** | /api/ps의 models가 비어 있음. 서버 기본값을 8192/40960으로 단정하지 않음 |

`/api/show`의 저장 parameters에는 num_ctx/num_predict가 없다. 저장 temperature는 0.6, 앱 요청은 기존대로 0.3이다. thinking 기본 true라는 모델 메타데이터와 앱의 명시적 think=false도 구분했다. 모델 목록의 tools/thinking 지원 표시는 실제 호출 품질 검증이 아니다.

공식 upstream Qwen3-8B 카드는 native context 32768, YaRN 확장 131072를 안내한다. 이 값과 로컬 artifact 40960, 앱 요청 8192는 서로 다른 범위다. 독립적인 공식 최대 출력 한도는 확인하지 못했다. [Qwen 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-8B), [Ollama show](https://docs.ollama.com/api-reference/show-model-details), [실행 중 모델 조회](https://docs.ollama.com/api/ps).

### 기존 입력 예산

`ModelInputBudgetPreparationTest`가 **현재 ConversationService와 OllamaLlmClient의 실제 직렬화 코드**를 사용했다. 시스템 프롬프트와 등록된 도구 세 개도 포함했다. 모델 응답은 mock으로 종료하고 실제 추론 supplier와 검색/계획 service는 호출하지 않았다. 입력 계산은 저장한 실제 서버 메타데이터와 기존 QwenTokenCounter를 사용했다.

모든 문항의 query/history를 실제 API로 운반하는 최소 요청을 만들었다. 연결되지 않는 persona·원문 fixture·후보·지역 필터·계획 상태를 전달한 것처럼 꾸미지 않았다. 따라서 아래 200개는 **현재 API 첫 요청의 예산 조사**이며, 전체 동결 입력을 충족한 200문항 평가가 아니다. 이 차이와 원래 입력 해시는 [case-connections.jsonl](case-connections.jsonl)에 있다.

| 예산 조사 범위 | PASS | EXCEEDED | UNVERIFIED | 수치 |
|---|---:|---:|---:|---|
| 기존 문항의 초기 API 요청 200개 | 0 | 200 | 0 | 입력 상한 7619~8586 + 출력 예약 1536 = 9155~10122 > 8192 |
| 이전 실행에 저장된 MOCK 검색 결과를 누적한 후속 입력 1개 | 0 | 1 | 0 | 입력 상한 16028 + 예약 1536 = 17564 > 8192 |
| 미래 도구 결과·비동기 계획 생성의 아직 없는 native 입력 | 0 | 0 | 2개 범위 | 검색·계획을 실행하지 않아 실제 입력을 만들 수 없음 |

**EXCEEDED는 보수적 상한이 현재 예산을 넘었다는 뜻이다. 실제 토큰 수의 초과를 실측한 것이 아니다.** 모든 계산은 CONSERVATIVE_BOUND이고 실제 토큰 사용량은 없다. PASS도 품질 합격을 뜻하지 않는다. 첫 요청부터 차단되므로 현재 실행 가능 호출 수는 0이다. 원문 절단·도구 삭제·context 증가로 숫자를 맞추지 않았다.

실제 평가 전에 같은 템플릿의 정확한 토큰화 방법을 검증하거나, 메모리·공식 한도·실행 옵션을 확인한 별도 context 변경안을 검토해야 한다. 이번에는 어느 변경도 적용하지 않았다. 미래 누적 결과와 추가 계획 호출은 매 호출 예산 검사를 통과해야 한다.

수치와 범위: [qwen-budgets.jsonl](qwen-budgets.jsonl), [초기 native 요청 예시](initial-wire-example.json), [집계](preparation-summary.json). 서버 메타데이터 요청 시간은 추론 latency로 사용하지 않았다.

## 3. 앱 GPT와 평가 judge의 구분

[configuration-inspection.json](configuration-inspection.json)에 코드와 허용한 환경 변수 이름만 조사했다. API 키 값은 읽거나 기록하지 않았다.

- **앱 GPT: 미선택**. OPENAI_MODEL 등 모델 한도 설정이 비어 있다. judge 설정을 복사하지 않았다. 모델 미선택 상태에서 모델별 한도·비용을 임의로 채울 수 없다.
- **기존 judge: gpt-4.1-mini**. datasets/v1.4.0/source/judge_config.json의 설정이며 RAGAS_JUDGE_MODEL로 별도 override한다. 앱 OPENAI_MODEL과 다르다. 이번 제안의 judge 호출은 0이다.
- 공식 judge 모델 페이지는 context **1,047,576**, 최대 출력 **32,768**과 입력/캐시 입력/출력 각각 **$0.40/$0.10/$1.60 per 1M tokens**를 안내하며 Deprecated 표시도 있다. 계정 접근·실제 지원 여부는 호출로 확인하지 않았고 대체 모델을 고르지 않았다. [공식 모델·한도·가격](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

앱 GPT를 사용하려면 사용자가 앱 모델 ID를 선택한 다음 다음을 확인해야 한다.

| 설정 | 필요한 확인 |
|---|---|
| LLM_PROVIDER=OPENAI, OPENAI_MODEL | 선택한 앱 모델과 endpoint 지원 |
| OPENAI_CONTEXT_TOKENS, OPENAI_MODEL_OUTPUT_LIMIT | **그 앱 모델**의 공식 context/최대 출력 |
| OPENAI_LIMITS_MODEL, OPENAI_LIMITS_SOURCE | 동일한 모델 ID, 공식 근거·확인 날짜 |
| OPENAI_MAX_OUTPUT_TOKENS | 승인한 출력 예약량. hidden reasoning 포함 모델은 이를 포함 |
| OPENAI_API_KEY, 선택적 OPENAI_BASE_URL | 안전한 설정·해당 계정 접근. 키 값은 보고서에 금지 |

앱의 `/responses/input_tokens` 연결은 기존 구현을 유지했다. 이번에는 OpenAI 입력 집계 endpoint도 호출하지 않았다. 모델별 실제 입력 확인값·실제 usage·가격 실측은 없다. [공식 입력 집계 문서](https://developers.openai.com/api/docs/guides/token-counting).

추가로 **기존 Python judge 호출에는 앱의 LlmCallGuard가 연결되지 않았고 출력 상한도 명시되지 않는다.** 로컬 SDK 3.3.0의 기본 max_retries=2도 확인했다. 따라서 judge 비용을 현재 코드만으로 엄격히 제한했다고 주장할 수 없다. judge를 켜려면 별도 입력/출력 예산·재시도 0·물리 요청 상한·모델 가용성과 사용자 승인을 먼저 확인해야 한다. 이번에 이 경로를 실행하거나 설정을 변경하지 않았다. 가격 계산식은 `(비캐시 입력×0.40 + 캐시 입력×0.10 + 출력×1.60)/1,000,000 USD`이며, 실제 토큰이 없어 예상 청구액으로 대입하지 않았다.

## 4. 기존 case ID와 실제 채점 가능 범위

**전체 동결 계약에 완전히 연결되는 문항은 0개**다. query/history를 운반할 수 있다는 것과 원래 조건·후보·원문·상태·persona까지 동일하게 평가할 수 있다는 것은 다르다. 연결된 것으로 가정해 점수를 내지 않았다.

| 대상 | 기존 문항 | 현재 가능한 관측/부분 검사 | 미지원·선행 조건 |
|---|---:|---|---|
| 검색·리랭킹 | PLACES 85개 | 서버 검색 결과가 나중에 실제 수집되면 artifact 동일성 확인 가능 | CIRCLE을 요구하는 전체 planningRequest가 원래 입력에 없음. REGION/도시/제외 조건 전달과 corpus 동일성 미확인. 임베딩 전/리랭킹 후 순위를 이 대화 API가 둘 다 반환하는 것도 아님 |
| 도구 선택 | 전체 200개 | 실제 native tool_calls/인자 기록. 일부 TEXT의 도구 미호출 검사 | search의 현재 query+limit 스키마가 동결 query+지역·제외 스키마와 다름. 이름만 같다고 기존 hard-args 점수 합격으로 바꿀 수 없음 |
| 계획 | PLAN 29개, PLAN_DIFF 19개 | 기존 모의 DRAFT 검증은 유지 | generate_plan/get_planning_job의 Job→DRAFT는 create_plan preview와 다름. 기존 PLAN/applied/proposalId·route matrix·수정/확정 계약으로 변환하지 않음 |
| 추가 질문 | CLARIFICATION 20개 | 자연어로 보완 요청을 할 수 있는 구조 | ask_clarification 도구와 해당 response type이 현재 등록되지 않음 |
| 설명 | TEXT 47개 중 **30개 부분 연결**, 17개는 기억 등 다른 계약과 연계 | 완료된 실제 모델 응답이 있어야 TEXT 타입·conversation ID·도구 미호출·실제 전달 근거에 한정한 설명 검사 가능 | 원래 persona·제공 contexts·시각 등을 API가 모두 전달하지 않음. 기존 전체 persona/근거 충실성 점수의 완료로 표시 불가 |

부분 설명 평가는 새 judge를 실행한 결과가 아니다. 실제 모델 답변이 없어서 현재 품질 점수는 산출하지 않았다. 필요 시 기존 rubric을 사용할 수 있지만 미전달 자료를 모델 근거로 넣어 판정하면 안 된다. 상위 검색 결과의 적합성·부정/상충 해석·계획 조건 준수는 이번 준비로 검증되지 않았다.

**200개 전부의 case ID·split·기대 type·연결 상태**는 [CASE_MATRIX.md](CASE_MATRIX.md), 그룹별 정확한 ID 목록은 [case-groups.json](case-groups.json), 원래 export 해시와 조건별 미지원 사유는 [case-connections.jsonl](case-connections.jsonl)에 기록했다. 부분 연결 30개 / 계약 차단 170개이며 이 수는 모델의 성공·실패 수가 아니다.

## 5. 사용자 확인을 위한 실행 제안

[execution-proposal.json](execution-proposal.json)은 approved=false, executed=false이다. 다음은 **예산 차단을 해결하고 범위를 승인한 뒤의 제안**이며 현재 자동 실행할 수 없다.

| 항목 | 제안 |
|---|---|
| 앱 모델 | 현재 로컬 qwen3:8b만. GPT 앱 모델 미선택으로 제외 |
| case ID | **MGR-SOCIAL-aquariums**, **MGR-SOCIAL-architecture** |
| 선택 기준 | development의 도구·상태·기억·추가 원문 fixture가 필요 없는 부분 TEXT 후보를 ID순으로 정렬한 첫 2개. 결과를 보고 고른 것이 아님 |
| 질문 | “반말 말고 존댓말로 이야기해 주세요.” / “오늘 대화는 좀 장난스럽게 해줘.” |
| 반복·동시성 | 각 1회, 동시성 1 |
| 제안 최대 추론 | **전체 2회**, 문항당 첫 응답 1회. 후속 대화·도구 실행·Job 생성 0 |
| judge | 호출 0. 기존 기준을 참조한 수동 설명 검토만 제안 |
| 예상 API 청구 | **$0**인 로컬 모델·judge 미사용 범위. 전력/GPU 비용은 미측정이며 무료 계산 자원을 뜻하지 않음 |
| 예상 지연 | **실측 없음**. 계획 가정으로 문항당 30~120초, 2개 직렬 60~240초 + 로드/준비 시간. 품질·지연 보장이나 장치 성능 측정이 아님 |

이 두 문항은 스타일 요청과 불필요한 도구 호출 여부의 작은 시작점일 뿐, 장소 근거·검색·리랭킹·계획 평가를 대표하지 않는다. 그 항목의 차단 목록은 위 표와 170개 ID 목록으로 남긴다.

현재 서버 기본은 대화 최대 6회 + 같은 턴의 비동기 계획 생성 최대 1회로 **요청당 최대 7회 추론**까지 가능하다. get_planning_job을 새 턴에서 묻는다면 별도 요청으로 더해진다. GPT일 경우 각 추론 전 입력 집계 요청도 따로 계산해야 한다. 서버 기본 한도를 이번 제안의 전체 2회 상한처럼 취급하면 안 된다.

따라서 실제 실행 전 **첫 응답 뒤 도구를 실행하지 않는 수집 경계와 전체 2회 상한을 모의 검증해야 한다**. 현재 앱 루프를 그대로 호출하면 이 제안의 경계를 보장하지 않는다. 새로운 실제 실행기는 이번에 구현·실행하지 않았다. 기존 HTTP connect/read timeout은 5초/240초이며 위 30~120초 가정과 같지 않다. timeout은 서버 추론이나 비동기 Job 취소 영수증도 아니다.

중단 조건: 사용자 승인 없음, 예산 EXCEEDED/UNVERIFIED, 모델 digest/템플릿/렌더러 변경, 예상 밖 tool_call, 전체 호출 상한 도달, 기록/usage 누락, timeout, 검색·저장·Job·운영 변경 필요. 자동 재시도와 유료 fallback은 허용하지 않는 안이다. 앱 GPT나 judge를 추가하려면 모델·ID 목록·반복·토큰/요청 상한·비용을 다시 제안하고 확인받아야 한다.

## 모의 검사와 보존 범위

신규 Python 준비 검사 **7개 통과**, Java 입력 예산 검사 **1개 통과**. 별도 LF 기준 체크아웃의 기존 Python **39개 통과**와 구분한다. Java의 200개 요청 계산은 정답 채점 200문항 실행이 아니다. [JUnit XML](junit/TEST-com.yollo.TravelMate.ModelInputBudgetPreparationTest.xml), [준비 검사 기록](preparation-tests.json), [검증 해시와 보존 범위](verification.json)를 참고한다.

생산 Java/Python 검색 코드, 모델·context 설정, 기존 예산 가드, 도구 등록/루프, 거리·순위·활성/후보 상한, DRAFT 검증/저장, 동결 데이터셋과 과거 보고서는 변경하지 않았다. 원래 로컬 미커밋 수집기도 덮어쓰지 않았다. [수집기 조사 목록](local-collector-inventory.json).
