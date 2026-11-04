# 답변·추천 이유·인용·도구 호출 평가

현재 공통 파이프라인과 등록 도구를 그대로 사용한다. 기존 `ConversationApiModule.execute()`와 `RunControl`을 재사용하며
라우팅 LLM, 설명 전용 LLM, 자동 judge를 추가하지 않는다. 삭제한 `.local-backups`나 과거 Windows 런타임 파일에 의존하지 않는다.

## 무엇을 검사하는가

- **형식:** OpenAI 평가 설정에서는 도구 인자 strict와 별도로 최종 `message/citations/answerKind/emotion/intent`에 JSON Schema를 적용한다. 토큰 계산에도 동일한 schema를 포함한다. 일반 서버와 평가 서버 모두 `JSON_SCHEMA_V1`을 기본으로 쓴다.
- **의도·호출:** 실제 `MODEL_TURN.toolCalls`의 이름·인자와 실행한 `TOOL_RESULT`를 대조한다. 사전 검색을 모델의 도구 선택으로 세지 않는다.
- **실행 결과:** 조회·생성 결과가 서버 데이터와 일치하고 추가·반복 호출이 없는지 확인한다. 접수·진행 중·실패·초안을 구분한다.
- **사용자 답변:** `message`를 `response_text`로 그대로 보고한다. 반응·선택 이유·불확실성·주장과 근거의 관계를 검수한다.
- **인용:** 실제로 LLM에 전달한 `selectedEvidence.original.chunk_text`에서 인용문과 장소·근거 ID·출처 ID를 대조한다. 생성 보충 문맥은 원문으로 인정하지 않는다.

`cases.json`의 정답·설명 예시·검수 기준은 LLM에 보내지 않는다. 현재 API에 없는 `decision_type/tool_type` 필드를 모델에게 새로 출력시키지 않는다.
이 값들은 기존 native 도구명과 최종 `answerKind`에서 평가기가 판정하는 정답 분류다.

## 새 기준 경로

```text
Travelmate/                       # 정상 작업 폴더의 최신 develop
  Server/TravelMate/              # 공유 소스로 evaluation 프로필 실행
  .env.evaluation.json            # 로컬 비밀 연결값, Git 제외
  .env.evaluation-budget.json     # 승인한 이번 실행의 정책, Git 제외
  Evaluation/
    datasets/conversation-smoke-v1/cases.json
    experiments/conversation-smoke/
    tracks/conversation/
    runs/conversation-smoke/<run-id>/  # 요청·응답·원장·이벤트·채점만 저장
```

DB·Redis·Kafka·검색 서버는 기존 평가 전용 인프라를 사용한다. 이 평가기는 새 계정·DB·Job을 몰래 만들거나 운영 서버를 종료하지 않는다.
`CONV-PLAN-create`를 실제 선택하면 실제 생성 요청이 발생하므로 명시적으로 허용한 실행 범위에서만 선택한다.

## 오프라인 동작 확인

저장소 루트에서:

```powershell
python Evaluation/tracks/conversation/run.py --config Evaluation/experiments/conversation-smoke/offline.json --bindings Evaluation/experiments/conversation-smoke/offline-bindings.json --preview

python Evaluation/tracks/conversation/run.py --config Evaluation/experiments/conversation-smoke/offline.json --bindings Evaluation/experiments/conversation-smoke/offline-bindings.json --mock-responses Evaluation/experiments/conversation-smoke/offline-fixtures.json --output-dir Evaluation/runs/conversation-smoke/offline-01
```

이 예시는 합성 응답과 관측 이벤트를 사용한다. 원문 텍스트는 동결 corpus에서 가져왔지만 모델이 실행한 결과가 아니다.
9개 기계적 검사 결과가 통과해도 `quality_pass_count=0`, `all_quality_passed=false`를 유지한다.
가짜 Job ID는 MOCK에만 사용하며 실제 존재하는 작업이라고 간주하지 않는다.

## 실제 서버에서 시작할 최소 두 사례

`live.template.json`은 처음부터 전 문항을 호출하지 않는다. 다음 두 사례만 선택한다.

1. `PLR-TM-palaces-03`: 제공된 청크로 이유·인용을 포함해 직접 답변.
2. `CONV-SEARCH-exclude-first`: 첫 후보를 실제 제외 조건에 넣어 추가 검색 도구 한 번 실행.

본인 Job ID나 새 계획 생성이 필요하지 않다. 서버 상한은 운영과 같은 6턴·8도구이며, 이 사례들은 모델 한 턴으로 끝나는지 `one_model_turn_observed`로 따로 기록한다.
두 번째는 새 도구 결과를 LLM이 다시 읽는 단계 없이 서버 영수증으로 종료하는 범위다.
그 영수증을 LLM이 새 결과를 읽고 작성한 상세 추천 설명으로 채점하지 않는다.

9사례 전체 실행은 `live.batch-a*.json`(조회·대화 7개), `live.batch-b-*.json`(일정 생성·Job 조회)을 사용한다.
B안 인프라 재사용 구성과 결과는 [2026-11-04 실행 기록](../../../docs/evaluation/tool-calling-live-20261104.md)을 따른다.

### 1. 같은 테스트 서버의 설정 확인

`Evaluation/experiments/server-environment.example.json`을 참고해 정상 작업 폴더의 `.env.evaluation.json`을 작성한다.
OpenAI 평가에서는 기존 `EVAL_OPENAI_*` 모델·키·공식 한도 설정에 더해 다음을 사용한다.

```json
{
  "EVAL_LLM_PROVIDER": "OPENAI",
  "EVAL_OPENAI_MODEL": "gpt-5.4-mini-2026-03-17",
  "EVAL_OPENAI_RESPONSE_FORMAT": "JSON_SCHEMA_V1"
}
```

대화 호출 상한(`max-model-turns`·`max-tool-calls`)은 평가 프로필에서 덮어쓰지 않고 `application.properties`의 운영 값을 그대로 쓴다.
실험 설정의 `max_model_turns`·`max_tool_calls`는 실행 중인 서버가 보고한 값과 같아야 하며, 다르면 대화 요청 전에 중단한다.
사전 검색 1회도 도구 호출 상한에 포함된다. 한 번의 모델 호출로 끝났는지는 `one_model_turn_observed` 검사로 따로 기록한다.
기동은 기존 공통 실행기를 사용한다. `--spring.config.location`으로 기본 설정을 대체하지 않는다.

```powershell
python Evaluation/evaluation_server.py --environment-file .env.evaluation.json
python Evaluation/evaluation_server.py --environment-file .env.evaluation.json --start
```

### 2. 이번 실행 정책과 인증 연결

`openai-budget.template.json`은 두 사례의 입력 해시·한도를 담은 **미승인** 예시다. 이전에 사용한 동일 모델의 단가 설정을 이어받았다.
실행하기로 확정한 모델·문항·호출/비용 한도에 맞춰 `.env.evaluation-budget.json`에 설정하고, 실제 실행 승인 전에는 `approved=false`를 유지한다.
승인한 정책의 절대경로를 `EVAL_OPENAI_BUDGET_FILE`에 연결한다. 원장 이름 `NEW-RUN`도 이번 실행의 고유 이름으로 바꾼다.
기존 원장은 삭제·덮어쓰기·재사용하지 않는다. 정책과 원장만 설정 파일로 관리하며 프로젝트나 JAR을 복사하지 않는다.

추론·계산 각 최대 2회이며 제안된 추론 예약 상한은 $0.023808이다. `ALLOW_UNVERIFIED` 계산 비용과 총 청구액은 null로 남긴다.
이를 총 청구액 $0.10 보장으로 해석하지 않는다. 일정 생성 사례를 추가할 때는 내부 비동기 계획 추론의 정책·횟수도 별도 확인해야 한다.

`TRAVELMATE_EVAL_ACCESS_TOKEN`에는 해당 격리 DB의 **aDMINuser** 토큰을 제공한다. 평가기가 JWT를 임의 발급하거나 다른 계정과 동일시하지 않는다.
비밀값은 요청·원장·Git에 넣지 않는다.

### 3. 사전 확인 후 실제 수집

```powershell
python Evaluation/tracks/conversation/run.py --config Evaluation/experiments/conversation-smoke/live.template.json --preview

python Evaluation/tracks/conversation/run.py --config Evaluation/experiments/conversation-smoke/live.template.json --execute-live --output-dir Evaluation/runs/conversation-smoke/live-01
```

`--preview`는 입력·해시를 읽기만 하며 서버에 연결하지 않는다. 서버 정책 작성에도 출력한 입력 해시를 사용한다.
실제 수집은 인증된 `GET /api/evaluation/conversation-contract` **1회**로 현재 도구 스키마·계정·모델·한도·JSON 형식을 먼저 확인한다.
이 endpoint는 evaluation 프로필에서만 제공하며 비밀값이나 DB 접속 정보를 내보내지 않는다. 잘못된 계정·모델·한도면 검색/모델 요청 전에 종료한다.

그다음 대화 요청 최대 2회를 순차 실행한다. 첫 서버 오류나 기계적 채점 실패·필수 관측 누락에서 후속 사례를 중단한다.
재시도·워밍업·judge·계획 생성은 이 기본 실제 범위에 없다. 원격 PC에서 실행하지 말고 테스트 서버의 이벤트 파일을 읽을 수 있는 로컬 Codex에서 실행한다.

서버가 반환한 절대 `observation_file`을 기본으로 사용한다. 다른 로컬 수집 경로라면 `--events <실제 execution.jsonl>`을 명시한다.
기록이 없으면 의미·도구 품질을 통과로 만들지 않는다. Spring 계약·검색 health 각 1회 확인과 앱 HTTP 호출 수는 내부 추론 호출 수와 별도로 기록한다.

## 결과와 내용 검수

```text
<run-id>/
  inputs.jsonl           # 실제 질문·조건·입력 해시, 정답 없음
  server-contract.json   # 이번 서버의 도구/응답 schema·계정 식별·모델·한도
  attempts.jsonl         # 전송 전 기록하는 공통 호출 원장
  records.jsonl          # 원본 HTTP 요청·응답·서버 종료 상태
  events.jsonl           # 이번 request ID에 해당하는 실제 서버 관측만 보존
  scores.jsonl           # 호출·인자·설명·인용·단계별 지연/관측 사용량
  review.csv             # 질문·실제 message·인용·전달 원문과 의미 검수 기준
  summary.json
```

기계적 통과와 내용 품질 통과는 다르다. `review.csv`의 각 기준에 실제 답변과 원문을 대조해 `PASS` 또는 `FAIL`, 검수자와 이유를 작성한다.
추천 이유·반응·주장 지지·불확실성 보존을 문자열 키워드 규칙만으로 통과시키지 않는다. 문장 예시와 글자가 달라도 의미가 맞으면 통과할 수 있다.

```powershell
python Evaluation/tracks/conversation/score.py --run-dir Evaluation/runs/conversation-smoke/live-01 --review Evaluation/runs/conversation-smoke/live-01/review.csv --output-dir Evaluation/runs/conversation-smoke/live-01/reviewed-01
```

실제 LIVE 모델 관측·모든 기계적 검사·모든 내용 검수가 갖춰지고 미실행 사례가 없을 때만 `all_quality_passed=true`다.
MOCK를 LIVE 품질로 올리지 않으며 검수 CSV는 정확한 원본 기록·이벤트 해시에 연결된다.
사전 검색·추론 HTTP·토큰 계산 HTTP·전체 대화 시간을 구분한다. 추론 HTTP 시간은 순수 GPU 계산 시간이나 요금이 아니다.

`CONV-JOB-owned`를 추가하려면 실제 본인 작업 UUID를 `{"owned_job_id":"..."}`로 제공하고 bindings 해시와 서버 정책을 갱신한다.
`CONV-PLAN-create`는 유효한 조건과 `allow_plan_creation=true`가 필요하며 실제 DB 작업·비동기 추론이 발생할 수 있다.
추가 문항은 기존 예산과 범위에 묵시적으로 포함하지 않는다. 지원하지 않는 수정·확정·예약 도구가 구현됐다고 기록하지 않는다.


## 네 단위를 따로 실행하기

`stage-order.json` 순서대로 `tool_call.offline.json`, `recommendation.offline.json`, `plan.offline.json`,
`conversation.offline.json`을 선택한다. 명령과 모듈은 같고 설정 파일만 교체한다.
각 실행에는 새 결과 폴더를 지정한다. Job 조회가 가능한 것은 계획 내용 품질의 통과와 다르다.
`plan_content.status=not_ready`이면 접수·진행 상태만 확인했으며 계획 품질 성공으로 세지 않는다.

실제 수집 전 두 서버의 소스 해시, 테스트 사용자, 모델과 GPU 장치가 맞아야 한다.
`live.template.json`의 expected_search_devices는 CUDA를 요구한다. CPU 대체 실행을 GPU 결과라고 기록하지 않는다.
현재 작업은 코드·평가기·모의 결과이며 실제 모델 품질이나 지연을 검증한 결과가 아니다.
전체 구성과 남은 한계는 [공통 아키텍처](../../../docs/architecture/unified-conversation-evaluation.md)를 따른다.


브라우저 연결만 모의로 확인하려면 클라이언트를 별도 포트로 실행하고 다음을 사용한다.
API는 모두 모의 처리하고 외부 요청을 차단하므로 실제 모델 품질·인증 성공을 뜻하지 않는다.
Playwright와 Chromium은 `Client/travel-mate-frontend/tests/requirements.txt`를 참고해 설치한다.

```sh
python Client/travel-mate-frontend/tests/browser_conversation.py --base-url http://127.0.0.1:15173
```

시스템 Chromium을 쓰려면 `--browser-executable <실제 경로>`를 제공한다. Windows/Linux 경로를 코드에 고정하지 않는다.

실제 평가 서버에 클라이언트를 붙일 때는 프록시 대상을 명시한다. 일반 서버 8080에 자동으로 붙여 평가하지 않는다.

```powershell
$env:VITE_PROXY_API_TARGET="http://127.0.0.1:18080"
npm --prefix Client/travel-mate-frontend run dev -- --port 15173
```
