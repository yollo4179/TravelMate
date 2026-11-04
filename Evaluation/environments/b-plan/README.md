> **과거 실행 기록용 환경입니다. 현재 공통 경로의 품질 검증에는 사용하지 않습니다.**
> 새 실행: `Evaluation/evaluation_server.py`, `Evaluation/evaluation_search_server.py`,
> `Evaluation/tracks/conversation/run.py`. Spring과 검색 서버의 실제 소스 해시가 정상 작업 폴더와 같아야 합니다.
> `run_b.py --execute`는 차단했습니다. 과거 원본과 검사·분석 함수는 보존합니다.

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

## 현재 GPU 검색 구성

2026-11-02에 평가 검색 서비스의 임베딩·리랭커를 CUDA로 전환했다. 아래 CPU 구성 설명과 이전 CPU 실행 기록은 당시 환경을 설명한다. 현재 구성을 재현할 때는 GPU overlay를 함께 사용한다. 기본 Compose만 적용하면 GPU 연결이 사라질 수 있다.

```powershell
docker compose --env-file Server/TravelMate/build/b-evaluation/runtime.env -f Evaluation/environments/b-plan/compose.yaml -f Evaluation/environments/b-plan/compose.reranker-gpu.yaml up -d --no-deps --pull never --no-build search
```

기존 진입점 `Docker/embedding-entrypoint.py`를 재사용한다. `/health`에서 실제 파라미터의 장치·dtype, 실행 전략·배치와 추론 횟수를 확인한다. Qwen은 미적재이며 GPU 전환 자체는 검색·추론을 실행하지 않는다. 소스 변경을 반영해 재시작할 때만 위 명령에 `--force-recreate`를 추가한다. 이전 CPU 보고서·관측 파일·DB를 덮어쓰지 않는다.

현재 배치 설정 8을 세 predict 전략에 명시적으로 전달한다. 이전 구현은 이 인자를 전달하지 않아 라이브러리 기본값 32를 사용했으므로, 과거의 설정 기반 batch_count와 실제 predict 배치를 구분해야 한다. GPU 전환·배치 전달 수정의 처리 시간과 순위 영향은 다음 승인된 검색에서 관측한다. FP16 전략으로 임의 전환하지 않는다.

OpenAI strict 서비스 구성 제안은 별도 `prepare_openai_service.py`로 생성한다. 이 도구는 실행 옵션이나 HTTP 호출을 제공하지 않으며, `approved=false`와 토큰 계산 과금 미확인 상태의 예산 파일을 만든다. 현재 `run_b.py`는 Qwen 프로필 전용이다. 이전 실행 runtime에 새 API 호출을 보내거나 기존 관측 파일을 재사용하지 않는다.

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

초기 준비에서는 창경궁(378)·올림픽공원피크닉장(311)에 구조화 청크가 없어 실행을 차단했다. 이후 별도 원문 필드 경로를 추가했다. `prepare_original_fields.py`는 동결 snapshot의 두 `places.description`이 generated corpus와 같고 실제 TourAPI content ID에 연결되는지 확인한 뒤 `place_original_field_evidence`에 그대로 보존한다. snapshot 버전·snapshot/corpus/manifest 파일 해시·장소 ID·content ID·UTF-8 내용 해시를 함께 저장한다. URL·수집 시각·리뷰·생성 문맥·관계는 만들지 않는다.

`PRESERVED_ORIGINAL_EVIDENCE=post-retrieval-field-v1`은 기존 장소 후보를 검색한 **뒤** 적합한 활성 근거가 없는 장소에만 해당 필드를 연결한다. 새 청크 벡터로 검색하지 않고 `vector_binding=NOT_EMBEDDED`, `semantic_score_scope=place_candidate`로 구분한다. 기본 설정은 disabled이며 평가 Compose에서만 활성화했다. 명시적인 observation 종류/이동 필터에는 미분류 원문을 붙이지 않고 기존 리뷰/관계 근거를 교체하지 않는다. 후보 재현율을 높이는 기능이 아니다.

새 임베딩 대상/호출 수는 **0개/0회**다. 원문은 별도의 벡터 대응을 주장하지 않으므로 기존 벡터를 복사해 청크에 붙이거나 새 모델로 계산하지 않는다. 활성 청크 슬롯·기존 장소 벡터·순위/거리/상한 정책은 바꾸지 않는다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/prepare_original_fields.py --runtime Server/TravelMate/build/b-evaluation
```

이 명령은 평가 DB 원문 결합 SELECT, 고정 모의 후보/점수의 근거 선택과 Kafka 직렬화만 실행한다. 실제 검색 요청이나 검색/리랭킹 모델을 호출하지 않는다. 생성한 `original-fields/mock-kafka-result.json`을 Spring 회귀 리소스로 재사용해 실제 파서·DTO·대화 도구·모의 LLM 입력을 검증했다. mock score 0.5는 품질 점수가 아니다.

새 Spring JAR를 오프라인 빌드한 뒤 아래 명령으로 기존 snapshot/JAR를 보존하고 별도 배포 manifest/JAR를 기록한다. `start-spring.ps1`는 이 manifest가 있으면 해당 JAR를 선택한다. 이미 실행 중이면 경로를 확인한 평가 프로세스 트리만 먼저 종료해야 한다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/prepare_original_fields.py --runtime Server/TravelMate/build/b-evaluation --record-deployment
```

선택한 평가 설정은 관계 검색 `chunk-and-relation-v1`, 근거 수 2, 후보 30·활성 20·공개 결과 최대 20, RERANKED다. 원본 가중치를 읽되 CPU `cross_encoder_predict`를 사용해 기존 GPU 서비스의 자원 배치를 바꾸지 않는다. 기존 실행 스택의 `autocast_fp16`과 다르므로 순위 점수 비교 가능 판정을 주지 않는다. 보존 벡터의 동일성은 역사적 임베딩 입력/생성 모델 전체의 재검증을 뜻하지 않는다.

## 관측과 호출 한도

`--profile gpu-two`는 계약·출력 지침 수정 후 기존 `PLR-TM-palaces-01`, `PLR-TM-palaces-03`만 각 1회 선택한다. 이 프로필은 Qwen 최대 4회·검색 최대 2회이며 원래 `original-four` 프로필의 8회·4회 상한과 구분한다. 두 프로필 모두 첫 실패에서 종료하고 기존 관측 파일·출력 디렉터리가 있으면 재실행을 거부한다. 새 JAR는 기존 runtime을 덮어쓰지 않고 별도 runtime의 `original-fields/deployment.json`에 연결한다.

```powershell
# 기본 동작은 추론·검색 없는 검사다. 이미 실행한 runtime을 재실행하는 명령이 아니다.
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/run_b.py --runtime Server/TravelMate/build/b-evaluation-gpu-retest --profile gpu-two
```

실제 dispatch 수는 실패한 모델 호출도 포함한다. `observed_search_tool_attempts`는 인자 검증에서 거부된 도구도 포함하므로 실제 검색 백엔드 요청 수와 같다고 간주하지 않는다. 후자는 DB 기록과 따로 대조한다. 준비 검사의 pending 수는 모든 과거 행 수가 아니라 unpublished outbox와 PENDING/RUNNING 작업 수다. 완료 행은 보존한다.

Qwen qwen3:8b·think=false·context 8192·출력 예약 1536을 유지한다. 검색 도구만 등록하며 요청당 모델 턴 2·도구 실행 1·실패 시 STOP이다. 기본 `original-four` 프로필은 기존 B안 네 문항만 각 1회, 직렬, 재시도 없이 보낸다. 이 프로필의 전체 상한은 Qwen 8회·검색 4회다. 서버의 제한은 요청별이며 배치 상한은 선택한 수집 프로필에 있다. 서버에 별도 요청을 보내면 이 범위 보장을 받을 수 없다.

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

원문 연결과 새 배포 해시까지 확인한 현재 환경에서는 준비 차단 목록이 비어 있다. 이는 실제 검색·설명 품질 평가의 통과가 아니다. 아래 실제 실행 명령은 **이번 데이터 연결 준비에서는 실행하지 않았다**. 실제 실행 범위를 확인한 뒤 사용한다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/run_b.py --runtime Server/TravelMate/build/b-evaluation --output Server/TravelMate/build/b-live-first --execute
```

HTTP timeout/실패는 결과가 없다는 뜻이 아니므로 재전송하지 않는다. 첫 예산·동일성·도구·검색·인용/최종 형식·관측 오류에서 배치를 멈추고 부분 기록을 남긴다. 실제 전달 후속 원문의 토큰 수·최종 품질·전체 지연은 미측정이다. 계획 Job·추가 계획 LLM·GPT·judge 호출은 실행 범위에 없다. 수정·확정·롤백·이동시간·동선 최적화도 평가하지 않는다.
