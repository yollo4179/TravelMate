# B안 격리 실행 환경

Spring은 **Windows 호스트**에서 실행한다. Spring이 검증된 Windows Python·libllama.dll·Go renderer를 자식 프로세스로 관리하고 `127.0.0.1:11434`의 기존 Ollama에 메타데이터/추론 요청을 보낸다. 계산기는 Linux로 이식하지 않았다. FastAPI와 두 DB·Kafka·Redis·로컬 OTLP 수집기는 전용 Compose 프로젝트 `travelmate-b-eval`에서 실행한다.

| 연결 | 평가 대상 |
|---|---|
| Windows Spring | `127.0.0.1:18080` |
| Spring DB | `127.0.0.1:55432/travelmate_b_spring`, 컨테이너 `tm-b-eval-springdb` |
| 검색 DB | `127.0.0.1:55433/travelmate_b_search`, 컨테이너 `tm-b-eval-searchdb` |
| Kafka | Windows `127.0.0.1:39092`, FastAPI `kafka:9092`, **별도 broker** |
| 토픽 | `travelmate.b-eval.place-changes.v1`, `travelmate.b-eval.recommendation-requests.v1`, `travelmate.b-eval.recommendation-results.v1` |
| Redis / FastAPI | `127.0.0.1:16379` / `127.0.0.1:18000` |
| OTLP | Windows `127.0.0.1:18318`, FastAPI `traces:4318` |

모든 공개 포트는 localhost에 바인딩한다. 기존 `docker` 프로젝트·볼륨·서비스·토픽은 재구성하지 않는다. 모델 캐시 `docker_stack_models`만 읽기 전용으로 공유하고, 나머지 저장소는 분리한다. 네트워크는 Windows의 공개 포트 접속이 가능한 별도 bridge다. 네트워크 자체의 외부 통신 차단을 주장하지 않는다. HF는 offline·읽기 전용이며 유료 모델 키를 전달하지 않는다.

아래 명령은 이 작업 브랜치 worktree의 루트에서 실행한다. 현재 PC 경로는 `C:/Users/SSAFY/AppData/Local/Temp/travelmate-general-relation-retrieval`이다. runtime에는 비밀번호·원문·벡터가 있으므로 Git에 추가하지 않는다. 기본 예제 경로는 이미 gitignore되는 `Server/TravelMate/build/b-evaluation`이다. 다른 PC에서는 검증한 Python·프로필·renderer 경로를 먼저 맞춰야 하며 현재 검증 범위를 일반화하지 않는다.

## 새 환경 준비 순서

초기화 명령은 새 runtime과 빈 평가 DB에만 실행한다. 이미 준비된 DB에 `load`를 반복하면 덮어쓰지 않고 실패한다.

```powershell
Set-Location C:/Users/SSAFY/AppData/Local/Temp/travelmate-general-relation-retrieval
Push-Location Server/TravelMate
.\gradlew.bat --offline --no-daemon --max-workers=2 bootJar
Pop-Location
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/prepare.py configure --runtime Server/TravelMate/build/b-evaluation --profile Server/TravelMate/build/runtime-token-profile.json
docker compose --env-file Server/TravelMate/build/b-evaluation/runtime.env -f Evaluation/environments/b-plan/compose.yaml up -d --pull never --no-build springdb searchdb redis kafka
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/prepare.py snapshot --runtime Server/TravelMate/build/b-evaluation
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/prepare.py load --runtime Server/TravelMate/build/b-evaluation --archive C:/ssafy/Travelmate/Evaluation/runs/contextual
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/prepare.py verify --runtime Server/TravelMate/build/b-evaluation
```

DB·Kafka 컨테이너가 healthy 상태가 된 뒤 다음 단계로 진행한다.

```powershell
$topics = @('travelmate.b-eval.place-changes.v1', 'travelmate.b-eval.recommendation-requests.v1', 'travelmate.b-eval.recommendation-results.v1')
foreach ($topic in $topics) {
  docker exec tm-b-eval-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic $topic --partitions 1 --replication-factor 1
  if ($LASTEXITCODE -ne 0) { throw 'Topic preparation failed' }
}
docker compose --env-file Server/TravelMate/build/b-evaluation/runtime.env -f Evaluation/environments/b-plan/compose.yaml up -d --pull never --no-build traces search
powershell -NoProfile -ExecutionPolicy Bypass -File Evaluation/environments/b-plan/start-spring.ps1 -Runtime Server/TravelMate/build/b-evaluation
```

`start-spring.ps1`는 corpus 검증·대기 작업 0·JAR 해시·중복 PID/포트를 검사한다. Spring의 환경 변수 우선순위로 기존 DB나 공급자가 선택되지 않도록 실행 프로세스의 관련 상속 변수를 제거한다. JVM은 숨김 창으로 실행하고 stdout/stderr와 PID를 runtime에 남긴다. 중지할 때는 runtime의 PID와 명령 경로를 확인하고 해당 프로세스 트리만 종료한다. 이 문서는 기존 스택을 중단하거나 볼륨을 삭제하는 명령을 제공하지 않는다.

## 자료와 비교 범위

`snapshot`은 기존 DB 두 개에 `BEGIN READ ONLY`로 접속해 장소/기존 벡터를 보존하고, 동결 corpus와 `ExistingPlace`의 모든 필드를 비교한다. 장소·버전·벡터가 포함된 전체 원본 행 해시와 JAR/소스 파일 해시도 남긴다. 원본 사용자·계획·작업·outbox는 복사하지 않는다. API 인증용 합성 사용자 1명만 평가 DB에 만든다. 이는 평가 근거가 아니다.

`load`는 기존 승인된 실제 P09 청담도로공원 record·승인 파일과 공개 보존 해시에 맞는 embedding cache만 읽는다. 기존 활성 선택 정책으로 8개를 적재하며 원문·주체·문맥·제한을 바꾸지 않는다. 기존 자료의 주체 지문이 다르거나 저장 벡터가 없으면 새 생성·추론으로 보충하지 않고 실패한다. A/B 합성 통제와 방해 자료는 ID가 실제 corpus와 겹치므로 적재하지 않는다. 현재 실제 자료에는 이동 관계 벡터가 없다.

창경궁(378)·올림픽공원피크닉장(311)에는 corpus의 기존 장소 설명·벡터는 있지만 보존된 구조화 청크/관계는 없다. 누락 근거를 장소 설명에서 새 청크로 만들어 채우지 않았다. 다른 실제 자료로 대체하지도 않았다. 따라서 현재는 인프라 준비와 B안의 원문 기반 설명 평가 준비를 구분한다.

선택한 평가 설정은 관계 검색 `chunk-and-relation-v1`, 근거 수 2, 후보 30·활성 20·공개 결과 최대 20, RERANKED다. 원본 가중치를 읽되 CPU `cross_encoder_predict`를 사용해 기존 GPU 서비스의 자원 배치를 바꾸지 않는다. 기존 실행 스택의 `autocast_fp16`과 다르므로 순위 점수 비교 가능 판정을 주지 않는다. 보존 벡터의 동일성은 역사적 임베딩 입력/생성 모델 전체의 재검증을 뜻하지 않는다.

## 관측과 호출 한도

Qwen qwen3:8b·think=false·context 8192·출력 예약 1536을 유지한다. 검색 도구만 등록하며 요청당 모델 턴 2·도구 실행 1·실패 시 STOP이다. 고정 수집기는 기존 B안 네 문항만 각 1회, 직렬, 재시도 없이 보낸다. 전체 상한은 Qwen 8회·검색 4회다. 서버의 제한은 요청별이며 전역 4문항 상한은 이 수집기에만 있다. 서버에 별도 요청을 보내면 이 범위 보장을 받을 수 없다.

Spring 원본 이벤트는 `observations/execution.jsonl`, 로컬 검색 span은 `traces/runtime-traces.jsonl`에 저장한다. 로컬 전송 검사 패킷은 별도 `traces/transport-probes.jsonl`에 저장하며 실제 문항·모델 기록으로 세지 않는다. 로컬 OTLP 연결을 활성화할 때만 사용하는 문자열은 외부 서비스 키가 아니다. 모든 exporter endpoint는 전용 로컬 수집기다.

로컬 미커밋 GET 검색 수집기는 덮어쓰지 않았다. 대화 API와 독립 검색 계약에 맞는 고정 수집기를 추가했고 기존 `common.dataset.io.export_inputs`와 `convert_server_trace`를 재사용한다. 원본 tool_calls와 평가 projection을 분리하며 `configuration_verified=false`를 전달한다. 변환 기록은 `recorded_not_scored`이며 설명 의미/순위/계획 품질 성공으로 처리하지 않는다.

## 준비 회귀 재현

다음은 모의 코드 검사이며 B안 실제 문항 실행이 아니다.

```powershell
docker exec tm-b-eval-search python -m unittest discover -s /workspace/Evaluation/environments/b-plan -p 'test_*.py' -v
```

## 실행 명령

현재 허용되는 준비 상태 확인은 **네트워크/모델 요청 없는 기본 실행**이다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/run_b.py --runtime Server/TravelMate/build/b-evaluation
```

현재 출력에는 `B_anchors_have_no_preserved_structured_evidence`가 남는다. 아래 실제 실행 명령은 **준비 작업에서 실행하지 않았다**. 원문 누락을 기존 보존 자료로 해소하고 DB·실행 설정을 재확인한 뒤 사용한다. 지금 입력하면 API 요청 전에 차단된다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/run_b.py --runtime Server/TravelMate/build/b-evaluation --output Server/TravelMate/build/b-live-first --execute
```

HTTP timeout/실패는 결과가 없다는 뜻이 아니므로 재전송하지 않는다. 첫 예산·동일성·도구·검색·인용/최종 형식·관측 오류에서 배치를 멈추고 부분 기록을 남긴다. 실제 전달 후속 원문의 토큰 수·최종 품질·전체 지연은 미측정이다. 계획 Job·추가 계획 LLM·GPT·judge 호출은 실행 범위에 없다. 수정·확정·롤백·이동시간·동선 최적화도 평가하지 않는다.
