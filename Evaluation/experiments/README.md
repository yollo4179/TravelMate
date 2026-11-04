# 모듈 교체 평가와 별도 테스트 서버

평가 코드는 하나이며 `EvaluationModule.execute(input, config, context)` 구현체를 레지스트리에서 선택한다.
`SEARCH_API`는 기존 독립 검색 수집기·필터·순위 채점기를 사용하고,
`CONVERSATION_API`는 테스트 Spring의 검색→근거 준비→단일 LLM 경로를 한 번 호출한다.
평가 실행기 앞에 라우팅 LLM이나 중복 검색을 추가하지 않는다.

## 서버 분리

운영 서버와 테스트 서버는 같은 소스를 사용하지만 **프로세스·포트·DB·Redis·Kafka broker/topic·검색 서버**를 분리한다.
테스트 프로필은 `Server/TravelMate/src/main/resources/application-evaluation.properties`다.
운영 `application.properties`는 변경하지 않는다. 테스트 프로세스는 루프백에만 바인딩한다.

1. `server-environment.example.json`을 참고해 저장소 루트의 Git 제외 파일 `.env.evaluation.json`에 실제 테스트 연결값을 작성한다. 예시에는 비밀값이 없으며 빈 값을 채워야 한다.
2. `EVAL_PRODUCTION_*`에는 비교할 실제 운영 주소를 지정한다. 운영 연결값을 테스트 기본값으로 사용하지 않는다.
3. 이미 준비한 격리 DB·Redis·Kafka와 별도 FastAPI 검색 프로세스를 연결한다. 이 도구는 DB 생성·복사·마이그레이션·테스트 계정 생성을 자동 실행하지 않는다.
4. FastAPI 검색 프로세스도 격리 검색 DB와 동일한 **evaluation** Kafka broker/topics를 사용한다. Spring의 토픽 이름은 `travelmate.evaluation.place-changes.v1`, `travelmate.evaluation.recommendation-requests.v1`, `travelmate.evaluation.recommendation-results.v1`이다. 모델을 버전마다 복제하거나 자동 다운로드하지 않는다.

저장소 루트에서:

```bash
# 설정 검사만 수행: 서버·HTTP·DB·모델을 시작하지 않음
python Evaluation/evaluation_server.py --environment-file .env.evaluation.json

# 명시적으로 테스트 Spring 프로세스 시작. 같은 소스를 bootRun하며 JAR/프로젝트 사본을 만들지 않음
python Evaluation/evaluation_server.py --environment-file .env.evaluation.json --start
```

실행은 전경 프로세스이며 해당 터미널에서 종료한다. 운영 서버를 찾아 종료하거나 기존 프로세스를 일괄 정리하지 않는다.
JDK 17 및 Gradle 빌드 의존성, 테스트 인프라는 별도로 필요하다. 설정 검사는 연결 가용성·DB 데이터 동일성·GPU 적재를 증명하지 않는다.

실행기는 자식 환경에서 `SPRING_*`, `SERVER_*`, `OPENAI_*` 등 일반 운영 override를 제거하고 `EVAL_*` 설정을 사용한다.
별도 JWT 키와 해당 테스트 DB의 실제 사용자로 발급한 토큰을 사용한다. 운영 토큰이나 계정을 자동 복사하지 않는다.
OpenAI 사용 시 `EVAL_OPENAI_*` 모델·한도·키·정책 파일을 지정한다. 기존 비용 가드를 그대로 사용하며 과금 미확인은 정책에서 명시적으로 표현한다.
정책에 지정된 기존 원장이 있으면 재사용·삭제하지 않고 시작 전 오류로 처리한다. Qwen은 별도 endpoint와 정확 계산기 설정이 필요하며 기동만으로 GPU/속도를 보장하지 않는다.

## 모듈과 설정의 경계

| 대상 | 선택 방법 | 실행 위치 |
|---|---|---|
| 검색 단독 / 대화 전체 | `variants[].module` → 구현 클래스 | Python 평가 실행기 |
| 임베딩 / 리랭킹 검색 | 같은 `SearchApiModule`에 `ranking_mode` 전달 | 기존 테스트 검색 서버 |
| OpenAI / Qwen, 모델·예산 | 평가 서버의 `EVAL_LLM_PROVIDER`, `EVAL_OPENAI_*`, `EVAL_OLLAMA_*` | 기존 Spring LLM 전략 |
| 근거 준비 | 기존 `ConversationEvidenceStrategy` 구현과 레지스트리 | 테스트 Spring |

임의의 Python/Java 클래스 경로를 JSON에서 import하지 않는다. 새 동작은 인터페이스 구현을 추가하고 레지스트리에 등록한다.
일치 구현이 0개 또는 여러 개면 실행 전에 실패한다. 단순 프롬프트·모델 차이를 위한 클래스 복제는 하지 않는다.

**`backend_profile`은 활성 서버 설정의 기록·대조값이며 서버를 원격 재설정하는 명령이 아니다.**
한 실행은 활성 프로필 하나만 사용한다. 모델·프롬프트·근거 구현을 바꾸려면 같은 테스트 서버의 해당 구현/설정을 변경하고 재기동한 다음, 확인한 runtime record와 해시로 새 결과를 수집한다.
무중단 클래스 교체, 새로운 근거 알고리즘, 모델 서버 자체의 호스팅은 이번 구현 범위가 아니다.
평가 실행기 안에 또 다른 검색→근거→LLM 파이프라인을 복제하지 않는다.

## 즉시 실행 가능한 오프라인 예시

```bash
python Evaluation/experiment.py --config Evaluation/experiments/search-offline.json --preview
python Evaluation/experiment.py --config Evaluation/experiments/search-offline.json --output-dir Evaluation/runs/module-check/offline-01
```

두 기존 궁궐 문항을 두 검색 모드로 검사한다. `offline-fixtures.json`은 **합성 HTTP fixture**이며 실제 검색/추천 품질 결과가 아니다.
원문·필터·기존 입력 해시를 유지하고 정확한 요청 본문 해시와 fixture를 대조한다.
MOCK에서는 HTTP 클라이언트나 인증 토큰을 읽지 않으며 검색 순위 품질 지표와 실제 지연 분모에서 제외한다.
같은 출력 폴더는 재사용하지 않는다. 새 폴더에는 결과 자료만 생기며 실행 환경이나 소스를 복사하지 않는다.

## LIVE 구성

구성 경로는 설정 파일 위치 기준이다. 현재 예시를 다음 조건에 맞춰 설정한다.

- `execution.mode=LIVE`, `fixtures=null`, `server_url`은 테스트 Spring 주소.
- `runtime_record`는 현재 테스트 서버를 확인한 기록이며 `runtime_sha256`과 `dataset_manifest_sha256`를 지정한다.
- runtime에는 `environment=evaluation`, 실제 `server_url`, `execution_mode=LIVE`, `corpus_sha256`, `backend_profile`이 필요하다.
- 비교 가능한 검색 순위 채점은 기존 `search-runtime-verification-v2` 계약의 자료·코퍼스·설정 대조까지 통과해야 한다. 확인값이 없으면 점수는 null이다.
- `token_env`로 지정한 환경변수에서 해당 테스트 사용자의 토큰을 읽는다. 토큰은 manifest나 원장에 기록하지 않는다.
- 대화 평가 variant는 `module=CONVERSATION_API`, `ranking_mode=null`, `response_limit=null`, `expected_response_type=PLACES`, `require_citations=true`로 설정한다. 대화 경로의 검색 개수는 서버가 관리하며 이 실행기의 검색 단독 설정으로 바뀌지 않는다.
- 검색 2모드×2문항은 `max_calls.search=4`, 대화 2문항은 `max_calls.conversation=2`다. 기본값으로 호출량을 늘리지 않는다.
- `execution.model`과 `max_output_tokens`는 기존 control 계약의 필드이며 이 실행기는 provider 직접 호출을 하지 않으므로 null을 유지한다. 실제 모델·출력 한도는 서버 설정/정책과 backend profile에 기록한다.

```bash
python Evaluation/experiment.py --config <현재-평가-설정.json> --preview
python Evaluation/experiment.py --config <현재-평가-설정.json> --output-dir <새-결과-폴더> --execute-live
```

`--execute-live`가 없으면 외부 요청 전에 거부한다. 실패 시 후속 문항·variant를 중단하며 재시도·judge·워밍업은 수행하지 않는다.
대화 요청은 서버가 근거를 준비하므로 평가기가 별도 검색 요청을 보내지 않는다.
`conversation` 상한은 앱 HTTP 요청 수다. 내부 검색·토큰 계산·추론의 상한은 **서버의 기존 가드와 정책**이 담당한다. 앱 요청 1회를 내부 추론 1회로 계산하지 않는다.
현재 테스트 프로필의 모델 턴·도구 실행 상한은 각각 1이며 일정 생성·상태 조회의 품질 평가를 완료했다고 표시하지 않는다.

## 결과와 판정

```text
<결과 폴더>/
  run.json                  # 커밋·설정/데이터 해시·구현 선택·원본 입력
  requests.jsonl            # variant/case별 실제 전송 예정 본문·바인딩 헤더
  attempts.jsonl            # 공통 호출 원장: 전송 전 기록, 실패도 상한 소비
  <variant>/records.jsonl   # 원본 HTTP 응답과 상태
  <검색 variant>/scores.jsonl # 기존 검색 채점기 결과
  summary.json              # 완료/실패·미실행·실제 관측 지연
```

대화 결과의 HTTP 200만으로 성공 처리하지 않는다. `COMPLETED`, `messageSource=LLM`, 모델 턴 1, 추가 도구 없음, 기대 타입과 인용 존재를 검사한다.
이는 **응답 계약 검사**이며 인용의 진위·주장 지지·의미 적합성 판정은 아니다.
대화 원본은 `conversation_http_experiment`이며 과거 `spring_execution_live` 기록으로 위장하거나 관측하지 않은 `tool_calls=[]`를 만들어 채점기에 넣지 않는다.
정식 native 채점은 서버의 실제 `execution.jsonl`을 추가 수집·변환해야 한다. 기존 변환기는 pre-retrieval 근거를 primary artifact로 사용하는 경로와 호환 여부를 따로 확인해야 한다.
관측하지 않은 내부 호출 수·계산 비용·총 청구액은 null로 유지한다. 서버 응답의 모델 턴 수는 provider 사용량 관측을 대신하지 않는다.
