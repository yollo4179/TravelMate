# B안 평가 환경 구성 — 실제 실행 전

2026-11-02 KST. Spring·FastAPI 핵심 코드 기준 커밋은 `edaa8a630806e6b7c1d89d93bcf163e91091a247`이며 환경 스크립트는 이 보고서와 같은 커밋에 있다. [실행·재현 안내](../../../../environments/b-plan/README.md).

**기존 실행 환경을 보존한 평가 인프라는 실행 중이다. 다만 B안 장소의 보존된 구조화 근거가 없어 실제 B안 요청은 차단했다.** 추론·임베딩 계산·리랭킹 계산·검색·대화 요청은 각각 0회다. 모델 가중치와 토크나이저 어휘는 준비 과정에서 로드했으며 이것을 추론 실행으로 세거나, 준비 검사를 답변 품질 평가로 세지 않았다.

## 실행 위치와 격리

| 구성 | 실행 위치·연결 | 확인 |
|---|---|---|
| Spring | Windows `127.0.0.1:18080`, JAR를 runtime에 동결 | 시작·OpenAPI의 새 대화/독립 검색 경로 확인 |
| 정확 계산기 | Windows Spring → 검증된 Python → libllama.dll·Go renderer | 현재 Spring 시작에서 READY 1회, Python/renderer 자식 상주 확인 |
| Qwen | 기존 Windows Ollama `127.0.0.1:11434`, qwen3:8b | 시작 시 버전·모델·템플릿·토크나이저 프로필 검증. 추론 없음 |
| Spring DB | `tm-b-eval-springdb`, `55432/travelmate_b_spring` | 별도 볼륨·계정. 장소 449건·인증용 합성 사용자 1명 |
| 검색 DB | `tm-b-eval-searchdb`, `55433/travelmate_b_search` | 별도 볼륨·계정. 기존 장소/벡터 449건·보존 실제 근거 |
| Kafka | `tm-b-eval-kafka`, Windows 39092 / 컨테이너 `kafka:9092` | 기존 broker와 분리. 전용 토픽 3개 오프셋 모두 0 |
| Redis | `tm-b-eval-redis`, localhost 16379 | 기존 Redis와 분리 |
| FastAPI | `tm-b-eval-search`, localhost 18000 | 최신 소스 read-only mount, 오프라인 모델 캐시, health=ok |
| 관측 | `tm-b-eval-traces`, localhost 18318 | 로컬 OTLP 수집. 원본 실행 이벤트는 Spring runtime 파일 |

모든 평가 컨테이너는 `travelmate-b-eval` 프로젝트에 속한다. 기존 `docker` 프로젝트의 서비스·볼륨·토픽을 교체·재시작하지 않았다. 모델 캐시만 read-only로 공유했다. 계산기의 Linux 이식은 하지 않았으며 Windows 검증을 Linux 검증으로 표시하지 않는다.

FastAPI는 기존 의존성 이미지 `travelmate-contextual-validation:64bf5ef0` (`3a29b6293640…`)를 재사용하되 최신 `embedding-server` 코드를 read-only로 마운트한다. 코드 출처와 이미지 출처를 구분했다. [컨테이너 ID·이미지 ID·마운트·연결 대상](container-readiness.json), [실제 소스 파일 해시](source-file-sha256.json), JAR 해시는 [corpus-comparison.json](corpus-comparison.json)에 있다. JAR은 Java 17 대상 코드로 오프라인 빌드했고 Windows의 설치된 JDK 21에서 실행했다.

네트워크는 분리된 bridge이며 모든 공개 포트는 localhost다. 외부 네트워크 자체를 차단했다고 주장하지 않는다. 모델은 HF offline/cache read-only로 로드했고 유료 공급자 키는 전달하지 않았다. 검색 컨테이너의 OPENAI·PERPLEXITY·LANGCHAIN·HF 키 비어 있음도 값 노출 없이 확인했다. 로컬 OTLP 활성화 문자열은 외부 서비스 키가 아니며 exporter의 목적지는 전용 로컬 수집기다.

## 보존 자료와 내용 비교

기존 두 DB는 `BEGIN READ ONLY`로 읽었다. 동결 corpus와 Spring·검색 DB를 ID뿐 아니라 `ExistingPlace` 전체 필드로 대조했다. 설명·지역·도시·분류·좌표·TourAPI ID·이미지·홈페이지를 포함한다. **449건 모두 누락·추가·변경 0건**이다. 정규화된 내용 SHA256은 세 자료 모두 `4040768ec8212348931395b82bee30d3790cd2c4473f4ccef2ce6389e36ed41b`다.

검색에 사용하는 원본 행의 source_version/latest_seen_version·저장 벡터·index_config_version도 스냅샷에 보존했다. 평가 DB의 Spring 원본 행과 검색 DB 기존 컬럼 전체가 원본 스냅샷 해시와 일치한다. 시간은 같은 Asia/Seoul 표기로 비교했다. source_version은 1, index_config_version은 `bge-m3-v1`이다. 이는 보존 벡터의 복사 일치이며 역사적 벡터 생성 입력 전체를 재검증한 것은 아니다.

- [corpus 비교](corpus-comparison.json) · [DB 적재·버전·대기 작업 검사](database-verification.json)
- [기존 DB의 준비 전후 행·벡터 해시 불변](source-preservation.json)

기존 실행 기록 중 **실제 장소 지문·승인·원본 응답·저장 벡터가 묶인 P09 자료**를 선택했다. 청담도로공원(394), v7 프롬프트 / validation-v4의 기존 승인 8개다. record·request·sources·raw_response에 묶인 기존 승인과 embedding cache의 공개 SHA256을 확인했다. 원문 2개·청크 8개·문맥/벡터 8개·활성 슬롯 8개를 적재했다. 생성 보충 문맥과 원문, 출처 metadata·place_refs·조건을 그대로 보존했다. 이 실제 승인 자료에는 이동 관계가 없어 관계 벡터 행은 0개다.

v8 재검증 기록과 과거 다른 프롬프트의 보존본도 확인했지만, 승인 범위를 새로 만들거나 여러 버전을 섞어 활성화하지 않았다. A/B 합성 통제·차량 방해 자료는 실제 corpus ID와 충돌하므로 적재하지 않았다. 기존 실험의 합성 관계를 B안의 실제 관계 근거로 바꾸지 않았다. [선택 자료·버전·지문·해시·누락](evidence-inventory.json).

창경궁(378)·올림픽공원피크닉장(311)은 기존 장소 설명과 벡터만 있다. 확인한 보존 원문/청크 아카이브에는 이 두 장소의 구조화된 근거가 없다. 없는 청크·출처·관계를 새로 생성하거나 394의 자료로 대체하지 않았다. 따라서 B안의 검색 후보 전송을 시험할 기반과 **해당 원문으로 설명하는 흐름의 평가 준비**를 구분한다.

## 검색 설정과 비교 가능성

| 항목 | 준비한 환경 | 기존 실행 환경과의 관계 |
|---|---|---|
| embedding | BGE-M3, revision `5617a9f…`, weights SHA `b5e0ce34…` | 기존 설정의 pinned revision/weight와 일치 |
| reranker | BGE-reranker-v2-m3, revision `953dc6f6…` | 로컬 파일 해시 기록. 추론 비교 없음 |
| 실행 전략 | CPU `cross_encoder_predict`, batch 8 | 기존 CUDA `autocast_fp16`과 다름 |
| 검색 표현 | `chunk-and-relation-v1` | 명시한 평가 설정. 실제 관계 자료는 현재 0개 |
| 리랭킹 근거 수 | 2 | 이전 관계 실측의 선택 설정. 기존 스택 기본값과 동일하다고 표시하지 않음 |
| 상한 | 후보 30·활성 20·API 최대 20 | 기존 정책 유지 |
| 순위 방식·거리 | RERANKED, 기존 Haversine 필터 | PostGIS 도입·도보 경로/시간 검증 없음 |

[가중치·토크나이저 파일 해시](search-model-assets.json). CPU를 사용해 기존 GPU 서비스의 배치를 바꾸지 않았다. 핵심 자료의 복사 일치만으로 기존 순위 점수와 비교 가능하다고 판정하지 않는다. 근거 범위·실행 전략·설정 차이가 있으므로 `ranking_scores_comparable=false`다. 기존 골든셋의 persona/provided_context 전체가 현재 API에 전달되는 것도 아니다.

## 계산기·관측·상한 검증

Spring은 `SEARCH_PLACES`만 허용하고 요청당 모델 턴 2·도구 실행 1·실패 시 STOP이다. 공급자 QWEN, qwen3:8b, think=false, context 8192, 출력 예약 1536을 유지한다. [비밀값 제외 구성](configured-settings.json). 매 호출과 누적 도구 결과 후속 호출의 전체 입력 가드는 기존 코드를 그대로 사용한다. 가드 해제·context 증가·원문 절단·유료 fallback은 없다.

현재 Spring PID와 Python 실행기/실제 worker/Go renderer 트리는 [worker-process-tree.json](worker-process-tree.json), 준비 기록은 [observation-readiness.json](observation-readiness.json)에 있다. 준비 중 로컬 수집기 설정을 추가하며 **평가 Spring만 1회 재시작**했으므로 전체 준비 과정의 초기화는 2번이다. 최종 Spring 시작에서는 초기화 1회(약 6.60초)이며 이전 인스턴스의 자식 트리도 함께 종료했다. 반복 계산·추론 지연을 다시 측정한 것은 아니다.

Spring의 `observations/execution.jsonl`은 B안 요청 전이므로 아직 없다. 기존 `ExecutionObservationTest`로 원본 이벤트 기록을 모의 검증했고, OTLP 모의 패킷은 별도 transport-probes 파일에 저장했다. 실제 runtime-traces의 준비 관측은 health와 FastAPI 처리 span이며 B안 모델/검색 관측으로 세지 않는다. 앱의 실제 도구 결과·인용·LLM 사용량은 아직 없다.

로컬 미커밋 검색 수집기는 보존했다. 기존 GET 수집기를 새 대화 API 수집기로 간주하지 않고 고정 B안용 `run_b.py`를 추가했다. 기존 export_inputs/convert_server_trace를 재사용하며 네 문항의 입력 해시가 기존 제안과 모두 일치함을 확인했다. 원본 호출과 옛 계약 projection을 분리하고 검색 설정 미일치/미검증을 성공으로 바꾸지 않는다.

- Windows 오프라인 bootJar 성공.
- 기존 JUnit 관측 1개·도구 루프 24개, 총 **25개 통과·실패/오류/건너뜀 0**. [집계](test-summary.json)와 같은 디렉터리의 JUnit XML에 기록했다.
- Python 준비 회귀 **13개 통과**: 준비/고정 수집기 안전 검사 10개와 모의 OTLP 전송 검사 3개다. 기존 DB 쓰기 금지, snapshot read-only, 덮어쓰기 거부, 원문 차이 지문, 잘못된 벡터 거부, 기본 비실행, 근거 누락 시 --execute 전송 차단, 반복 도구/누락 관측 거부, 실패 패킷 거부·gzip·모의 기록 분리를 확인했다.
- 실제 B안 요청·Qwen 추론·임베딩/리랭킹 계산·검색·계획 Job·GPT/judge·유료 호출 **모두 0회**. [실행 준비 판정](execution-readiness.json).

초기 적재 검사는 시각 표기 차이와 place-change 트리거 이벤트 449개를 발견했다. 평가 워커/Spring을 시작하기 전에 평가 DB 이벤트만 제거했고, importer에 trigger 억제와 시간대 통일을 반영했다. 최종 대기 outbox·검색/색인 작업·토픽 메시지는 모두 0이다. 최초 internal 네트워크는 Windows 공개 포트 접속이 되지 않아 평가 컨테이너/네트워크만 bridge로 재구성했고 평가 볼륨은 유지했다. 기존 스택은 이 조치의 대상이 아니었다.

## 재개 명령과 남은 차단

현재 준비 환경의 runtime은 다음 위치다.

```text
C:/Users/SSAFY/AppData/Local/Temp/travelmate-general-relation-retrieval/Server/TravelMate/build/b-evaluation
```

기본 검사는 네트워크·모델 요청 없이 준비 판정만 읽는다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/run_b.py --runtime Server/TravelMate/build/b-evaluation
```

**남은 실제 실행 차단은 `B_anchors_have_no_preserved_structured_evidence`다.** 이미 보존된 올바른 자료로 누락을 해소하고 연결 설정/DB를 재검증하기 전에는 아래 명령도 API 요청 전에 실패한다. 이번 준비 과정에서는 --execute를 실제 네트워크 경로로 실행하지 않았다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/run_b.py --runtime Server/TravelMate/build/b-evaluation --output Server/TravelMate/build/b-live-first --execute
```

조건이 충족되면 기존 B안 `PLR-TM-palaces-01/03/04`, `PLR-TM-family_parks-04`만 각 1회·직렬·재시도 없이 실행한다. Qwen 최대 8회·검색 최대 4회이며 서버 제한은 요청별, 배치 제한은 수집기에서 적용한다. 첫 동일성·예산·도구·검색·최종 형식/인용·관측 실패에서 중단하고 부분 기록을 보존한다. HTTP timeout도 자동 재시도하지 않는다.

현재 인증 포함 대화 API 전체 왕복, 실제 검색 원문 후속 입력의 토큰 예산, 실제 사용량·질문별 지연·순위·설명 의미는 미검증이다. 로컬 모델의 외부 API 사용료는 없지만 실제 실행 시간/CPU 비용은 측정 전이므로 0으로 가정하지 않는다. 순위 품질 점수와 계획 품질 완료를 주장하지 않는다. 새 문항·반복·judge·계획/수정/확정/롤백·실제 이동시간·동선 최적화는 이번 범위에 추가하지 않았다.
