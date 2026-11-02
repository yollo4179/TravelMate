# 실제 모델 평가 전 토큰 예산·평가 기록 연결

2026-11-01. 기준 커밋 `db38be73`, 작업 브랜치 `feat/contextual-general-relation-retrieval`.

대화와 비동기 계획 생성에 모델 호출 전 예산 검사를 연결하고, 실제 서버 실행 관측을 기존 평가 기록으로 변환하는 기반을 구현했다. 실제 모델 평가·검색 품질 개선·계획 품질 검증의 완료를 뜻하지 않는다. 실제 모델 추론·유료 호출·검색 재실행·운영 DB 반영·배포는 하지 않았다.

## 변경

1. GPT/Qwen 공급자 전략을 유지하고 양쪽 `chat()`과 `generate()`를 공통 `LlmCallGuard`로 감쌌다. 최종 공급자 입력 전체와 출력 예약량을 검사한다. 초과·미확인 계산이면 추론 전에 실패한다. 원문·부정·조건을 자르거나 유료 재시도하지 않는다.
2. GPT는 Responses 입력 토큰 집계 API를 연결했다. 대화 이력·시스템·도구·누적 결과·reasoning continuation이 같은 입력으로 집계된다. context/최대 출력은 정확한 모델에 묶인 설정과 출처가 없으면 차단한다. GPT 모델은 임의로 선택하지 않았다.
3. Qwen은 알려진 템플릿과 tokenizer의 보수적 상한만 허용한다. 정확한 토큰화 결과가 아니며 `CONSERVATIVE_BOUND`로 기록한다. 실제 reported usage와 구분하고, 미지원 프로필은 중단한다.
4. 요청·턴·모델 호출·실제 tool_calls/인자·도구 결과·최종 응답·종료·시간·사용량을 기록한다. 서버 type/data와 LLM 설명의 출처를 구분한다. `generate_plan`이 접수한 비동기 호출에도 부모 request/turn/tool_call과 jobId가 이어진다.
5. 기존 case_id/export 해시 규약을 재사용하는 오프라인 변환기를 추가했다. 실제 API 본문·해시·conversation ID·서버 결과를 대조한다. MOCK/LIVE를 구분하고 누락 관측과 계약 불일치를 품질 성공으로 계산하지 않는다.
6. Windows에서 manifest의 경로 키를 POSIX 표기로 고정했다. JSONL은 LF 경계로 읽어 원문 안의 U+0085/U+2028/U+2029를 훼손하지 않는다. 데이터셋 문항·정답·판정 기준을 변경하지 않았다.

자세한 설정·알고리즘·제약은 [구조 문서](../../../../../docs/architecture/token-budget-and-execution-observations.md)에 기록했다.

## 모델·한도 조사

| 항목 | 확인한 내용 | 확인하지 않은 내용 |
|---|---|---|
| GPT | 설정 모델 없음. 출력 예약 기본 1536. 새 context/output cap 기본 0으로 미설정 시 차단 | 실제 모델별 제원·count endpoint 접속/지원·실제 사용량·비용 |
| Qwen | 기존 qwen3:8b / think=false. 클라이언트 context 8192·출력 예약 1536. 로컬 GGUF 헤더 context 40960 및 gpt2/qwen2 byte BPE | 실행 중 Ollama 서버와 num_ctx, 실제 tokenizer count·품질·지연 |
| Qwen 출력 | context에서 유도한 상한과 요청 num_predict | 독립적인 공식 모델 최대 출력 한도 |

로컬 manifest SHA-256은 `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, 모델 레이어 digest는 `a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f`, 템플릿 SHA-256은 `ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4`였다. 파일 메타데이터만 조사했으며 모델을 로드하거나 API로 추론하지 않았다. 실행 때는 `/api/show` 응답으로 프로필을 다시 확인한다.

Qwen 상한은 byte BPE와 고정 템플릿의 모든 분기 확장을 과다 계산한다. 글자 수를 정확한 토큰 수로 표시하지 않는다. 실제로 들어갈 요청도 보수적으로 거부할 수 있다. GPT output usage에 포함된 reasoning을 추가 비용 토큰처럼 이중 합산하지 않는다. 공급자가 usage를 주지 않으면 null로 보존한다.

## 모의 회귀 결과

| 검사 | 결과 | 의미 |
|---|---|---|
| Java 선택 회귀 11개 클래스 | **82개, 실패 0·오류 0·건너뜀 0** | 도구 루프·기존 원문/인용·DRAFT 검증·공급자·예산·비동기 컨텍스트 검사 |
| 신규 Python 기록 연결 검사 | **12개 통과** | 바인딩/해시/모드/서버 artifact/미관측/Unicode/유료 judge 차단 |
| 기존 포함 Python 전체 | **39개 중 38개 통과, 실패 1·오류 0** | 아래 기존 보존 파일 바이트 해시 한계 포함. 전체 통과로 표시하지 않음 |
| Java MVC → 실제 MOCK JSONL → Python 변환 | 통과 | 서버가 실제 생성한 모의 이벤트와 기존 export 입력 연결 |

Java는 MockRestServiceServer·Mockito·standalone MVC·실제 Executor를 사용했다. Spring 운영 서버·DB·검색 서버·실제 모델에 연결하지 않았다. 기존 도구 반복/캐시/종료 검사도 포함했다. 비동기 검사에서 첫 응답은 PLANNING_JOB, 작업 완료 후 별도 조회는 저장소 모의 DRAFT였고, 추가 생성 호출은 원래 request-one/turn-one/generate-call/jobId에 연결됐다. 이는 실제 DB 저장이나 이동시간 검증이 아니다.

Java가 내보낸 [events.jsonl](events.jsonl)·[bindings.jsonl](bindings.jsonl)을 기존 `PLR-TM-palaces-01`의 [export](exported-inputs.jsonl)와 대조해 [records.jsonl](records.jsonl)로 변환했다. 기존 문항 하나를 기술적 모의 바인딩에 재사용한 것이며 새로운 실제 평가 범위가 아니다. 모의 장소·조건·검색 결과는 정답 품질을 판정하기 위한 자료가 아니다.

이 모의 흐름에서는 첫 모델 응답이 search_places를 요청하고 전체 원문·생성 문맥을 도구 결과로 받았다. 두 번째 입력 확인값을 의도적으로 한도 밖으로 만들어 실제 두 번째 추론 요청이 발생하지 않았다.

- 완료된 예산 검사 기록 2개, 모의 추론 dispatch 1개, 모델이 반환한 tool_call 1개.
- 종료 사유 BUDGET_REJECTED. 서버 장소 결과와 원문은 유지했다.
- 모델 사용량은 mock 응답에서 제공한 값만 기록했다. 실제 토큰 사용량이나 비용 실측이 아니다.
- 검색·도구·계획·상태·메시지 품질 coverage는 모두 false. 품질 점수는 null이다.
- server_data_unchanged=1은 전달 artifact의 구조적 동일성 검사 결과다. 추천 장소가 적합하다는 판정이 아니다.

세부 결과: [변환 검증](adapter-verification.json), [JUnit 집계](junit-summary.json)·[원본 XML 디렉터리](junit/), [Python 로그](python-tests.txt).

Python 전체 회귀의 실패는 보존 파일 원시 바이트 검사 한 항목이다. 147개 파일을 추가 대조한 결과 기존 `.gitattributes` 3개와 requirements 2개의 작업 트리 CRLF가 저장된 LF 해시와 달랐다. **다섯 파일 모두 기준 커밋의 blob은 기대 해시와 일치하고, 작업 파일도 LF로 해석하면 그 blob과 같다.** 해당 파일과 과거 manifest는 수정하지 않았다. [바이트 진단](archive-byte-diagnostic.json)에 공개했다. 첫 실행의 SDK 미설치/기본 cp949 오류는 기존 `.venv-ragas`와 `-X utf8` 실행으로 해소했으며 최종 실패와 구분한다.

## 평가 연결의 범위

원래 로컬 작업 트리의 미커밋 collect_live.py/collect_holdout.py와 평가 실행기를 먼저 읽었다. 검색 REST 수집 기능은 재사용할 수 있지만 대화·Job 관측을 이미 수집하는 것으로 취급하지 않았다. 공통 I/O·canonical 입력 해시를 재사용하고 별도 native 변환기를 만들었다. 원래 작업 파일은 덮어쓰거나 복사하지 않았다. [읽기 전용 조사 목록](local-collector-inventory.json)을 남겼다.

다음은 아직 평가 성공으로 만들 수 없다.

- 기존 PLAN/create_plan 계약과 현재 PLANNING_JOB/DRAFT·generate_plan/get_planning_job의 차이.
- 없는 plan_before/after, commit version, memory 상태, 실제 도로 비용 기록.
- 구조화 조건의 완전한 대응, 실제 corpus/검색 설정 동일성 확인 없는 순위 평가.
- 실제 모델이 근거의 귀속·부정·상충·과거 시점을 올바르게 설명하는지에 대한 의미 평가.

변환기는 실제 모델 tool_calls를 검증 전에 보존하고, 서버 publicData와 LLM에 준 modelData를 나눠 보존한다. 중간 실패를 빈 도구 호출 성공으로 바꾸지 않는다. native MOCK 설명이나 관측이 없는 설명으로 유료 judge를 생성하지 않는다. 실행 기록만으로 전체 검색·계획 품질이 완성됐다고 판정하지 않는다.

## 유지·남은 한계

검색 순위·리랭커·거리·활성 20개·후보 상한·원문 전달·DRAFT 공통 검증·계획 저장 규칙은 변경하지 않았다. 일정 수정·확정·롤백·실제 이동시간·동선 최적화도 추가하지 않았다. 변경 소스와 보존 범위 확인은 [verification.json](verification.json)에 기록했다.

토큰 예산 가드와 관측 연결은 구현했으나 실제 실행 준비가 모두 끝난 것은 아니다. 실제 GPT 모델과 제원·출력 예약, Qwen의 실행 서버 프로필과 보수적 예산으로 수용 가능한 입력, 실제 평가의 기존 문항 선택·반복·비용을 다음 실제 실행 전에 확정해야 한다. 이번에는 그 범위를 임의로 정하거나 실제 호출하지 않았다. 서버 로컬 JSONL의 회전·보존 기간·다중 인스턴스 수집과 재시작을 넘는 trace 복원도 남았다.
