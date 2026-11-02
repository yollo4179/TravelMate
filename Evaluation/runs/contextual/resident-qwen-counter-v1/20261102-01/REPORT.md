# Qwen 토큰 계산기 상주·재사용

기준 `5f9e1238`, 2026-11-02. 매 실제 LLM 호출마다 Python을 생성하던 경로를 Spring 생명주기에 연결된 상주 worker로 변경했다. **실제 모델 추론·검색·메타데이터 API·유료 호출·운영 DB 반영·배포는 실행하지 않았다.** 실제 검증은 저장 메타데이터와 로컬 어휘 전용 토크나이저를 사용했다.

## 변경한 동작

```text
Spring 시작: Qwen 선택 + 계산 명령 설정
  → 현재 서버 메타데이터 확인 → Python 시작 → INIT 검증
      → manifest/모델/DLL/renderer 해시 확인
      → native 어휘·독립 BPE 초기화 → READY

요청마다: 현재 서버 메타데이터 + 전체 native wire
  → 제한된 대기열 → requestId로 COUNT 전달
  → 파일/모델/템플릿 확인 → 같은 토크나이저로 전체 입력 재계산
  → token-ID·원문 바이트 대조 → requestId/sessionId 확인
  → 기존 가드가 입력 + 출력 예약량 검사 → 허용된 경우에만 LLM 호출

Spring 종료: worker·Go 보조 프로세스·파이프·통신 스레드 정리
```

`OllamaLlmClient`의 `@PostConstruct`/`@PreDestroy`가 계산기 초기화·종료를 관리한다. Qwen이 선택되지 않았거나 명령이 기본 `[]`이면 시작하지 않는다. 초기화 실패 시 LLM 호출을 허용하지 않고 실패 상태를 유지한다. 대화와 비동기 계획의 추가 LLM 호출은 계속 같은 전략·가드를 사용한다.

`ExactQwenProcess`는 UTF-8 JSONL 파이프로 하나의 Python worker와 통신한다. 요청마다 새 프로세스나 임시 입력 파일을 만들지 않는다. Python은 `QwenTokenizerSession`의 native 어휘와 독립 BPE를 재사용한다. 기존 Go renderer도 보조 프로세스 하나로 유지한다. Go 템플릿 실행 파일·프로필의 검증 해시는 변경하지 않았다. 직접 실행하는 기존 단발 CLI는 소급 검증용으로 보존했고 Spring이 명령에 `--serve`를 자동 추가한다.

## 동일성·장애·대기열 정책

- 전체 파일 해시와 어휘 로드는 시작 시 한 번 수행한다. 요청 전후에는 모델·DLL·renderer·manifest·프로필 파일의 파일 ID/크기/mtime/ctime을 확인한다. 매회 모델 전체를 재해시하지 않는다.
- 서버 모델 digest·버전·템플릿·tokenizer metadata는 매 LLM 요청의 새 메타데이터로 확인한다. 다른 프로필을 자동 승인하지 않는다. 로컬 파일이나 서버 동일성이 바뀌면 기존 인스턴스를 무효화하고 해당 호출을 차단한다.
- 토큰 수·입력 결과 캐시는 없다. 원문·부정·조건·이력·도구 정의·누적 도구 결과를 매번 전체 토큰화한다. 같은 입력도 새로 계산하며 native/독립 BPE의 모든 ID와 원문 바이트 복원을 다시 대조한다.
- 기본 대기 슬롯 8개와 활성 계산 1개를 사용한다. `ollama.exact-counter-queue-capacity`, `ollama.exact-counter-queue-timeout-millis`로 제어한다. 대기 제한 기본값은 5000ms이며 `QUEUE_TIMEOUT`은 다른 요청의 활성 정상 계산을 종료하지 않는다.
- worker 초기화 `STARTUP_TIMEOUT`과 계산 `CALCULATION_TIMEOUT`을 구분한다. 기본 worker 시간 제한은 기존 90초다. 내부 renderer 시간 초과도 계산 시간 초과로 전달한다.
- 프로세스 종료·계산 실패·응답 ID 불일치·동일성 실패는 호출을 차단하고 프로세스 트리를 종료한다. 장애 전에 대기하던 요청은 `SESSION_INVALIDATED`로 실패시킨다. 그 요청을 새 worker에서 자동 재실행하지 않는다.
- 다음 **새 요청**에서만 새 worker의 검증·초기화를 한 번 시도한다. 재검증 전 예전 토크나이저를 사용하지 않는다. 추론이나 유료 호출은 자동 재시도하지 않는다.
- `counterRequestId`, `workerSessionId`, worker PID, 초기화 횟수, sequence, `initializationMs`, `calculationMs`, `queueWaitMs`, `transportCalculationMs`를 기존 count evidence에 보존한다. 초기화 시간은 세션별 값이므로 요청마다 합산하면 안 된다.

context 8192·출력 예약 1536, 전체 입력 검사, 미지원 차단, 원문 보존, 기본 검색·계획 조건은 유지했다. 가드를 해제하거나 context를 늘려서 실행하지 않았다.

## 검증

| 검증 | 결과 |
|---|---|
| 지정 Java 모의 회귀 | 94개 통과, 실패·오류·건너뜀 0 |
| Python 회귀 | 34개 통과, 실패·오류·건너뜀 0 |
| 기존 저장 native 요청 | 8개를 같은 worker에서 2회씩, 총 16회 계산 |
| 이전 결과 비교 | 16개 모두 wire·template·prompt·token-ID 해시와 정확 토큰 수 일치 |
| 재사용 | 같은 worker PID·sessionId, 초기화 1회, 계산 sequence 1~16 |
| 정상 EOF 종료 | worker 정상 종료 확인 |

Java에서는 재사용·원문 전체 전달·요청 ID 연결, 큐 용량/대기 초과, 초기화/계산 시간 초과 구분, 오래 대기한 요청의 무효화, 프로세스 충돌·응답 ID 불일치·동일성 거부 후 재초기화, 종료와 Spring 생명주기를 검사했다. 기존 원문·인용·검색·도구 루프·Job→DRAFT·초안 검증도 모의 회귀로 확인했다.

Python에서는 어휘/BPE/renderer의 생성이 한 번뿐인지, 입력 변경과 동일 입력 반복 모두 실제 encode를 거치는지, 파일·템플릿 변경이나 ID 불일치 후 인스턴스가 폐기되는지, INIT/COUNT/EOF와 오류 후 종료를 검사했다. 실제 대형 모델 파일을 변경한 검사는 하지 않았다.

## 초기화와 반복 계산 시간

측정 입력은 [이전 보고서의 native wire 8개](../../runtime-qwen-independent-search-v1/20261102-01/current-native-wires.jsonl) 그대로다. 네 기존 문항의 최초 요청과 모의 원문 결과 후속 요청이며 실제 검색 결과가 아니다. 새 평가 문항·실제 모델 반복을 추가하지 않았다.

| 단계 | 실측 |
|---|---:|
| worker 내부 초기화 | 5571.75ms |
| 실행기 시작부터 READY 수신 | 5720.76ms |
| 초기화 후 계산·통신 최소 / 중앙 / 최대 | 5.58 / 9.70 / 13.63ms |
| Python 내부 계산 중앙값 | 9.12ms |

이전 기록의 5649.90~6151.54ms는 매 호출의 해시·어휘 초기화가 포함된 시간이었다. 이번에는 그 비용을 시작 시 한 번 지불한다. 초기화와 반복 계산을 합쳐 같은 지표로 비교하지 않는다. 단일 Windows 환경과 고정 입력의 소규모 오프라인 측정이며, 실제 LLM/검색 지연이나 서비스 p95·SLA로 일반화하지 않는다. 현재 서버 메타데이터 조회·Java 대기열의 실제 부하 시간도 이 측정에 포함되지 않는다.

Windows 가상환경에서는 실행기 PID와 실제 Python PID가 다를 수 있다. 재사용 여부는 READY의 worker PID와 sessionId를 이후 모든 응답과 대조했고, 실행기 PID와 worker PID를 각각 기록했다. 측정 데이터는 `benchmark/ready.json`, `benchmark/counts.jsonl`, `benchmark/summary.json`에 있다.

재현 명령은 검증한 tokenizers 0.22.2 환경에서 다음과 같다. 출력 경로가 이미 있으면 덮어쓰지 않는다.

```text
python -X utf8 Evaluation/tracks/tool_call/benchmark_resident_qwen.py --profile <검증한 로컬 profile.json> --output <새 출력 디렉터리>
```

## 남은 한계와 범위

Windows AMD64 / Ollama 0.40.13 / qwen3:8b / think=false의 기존 검증 프로필만 지원한다. 다른 모델·템플릿·플랫폼은 차단 상태다. 매회 전체 파일 해시를 검사하는 대신 파일 식별 정보의 변화를 감지한다. 서버 메타데이터 조회와 이후 추론은 원자적이지 않다.

실제 서버 `prompt_eval_count`, 실제 검색 원문 후속 입력의 예산, 동시 운영 부하와 장시간 메모리 사용량은 아직 검증하지 않았다. 큐 초과/장애 처리는 모의 검증이다. 초기화 때의 서버 메타데이터 조회 시간은 worker 자체 90초 제한과 별도의 기존 HTTP 제한을 적용받는다.

기본 명령 `[]`은 계속 호출을 차단하며 운영 설정은 적용하지 않았다. B안의 기존 4문항·Qwen 최대 8회·검색 4회는 실행하지 않았다. 실제 추론은 계속 보류한다. 이 상주화 검증은 검색·계획·설명 품질 평가 완료가 아니다. 동결 골든셋·manifest·기존 실측 보고서와 로컬 미커밋 수집기는 수정하지 않았다.
