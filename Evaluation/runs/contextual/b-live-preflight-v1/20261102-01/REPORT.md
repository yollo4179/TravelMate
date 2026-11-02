# B안 실제 연결 검증 전 환경 확인

기준 코드: `642d45fb4c80bc0fa2f8ba32b958fb00fa351647`. 확인일: 2026-11-02 KST.

**기존 실행 환경이 B안의 전제 조건을 충족하지 않아 실제 평가 요청 전에 중단했다.** Qwen 추론·검색 도구 실행·대화 API 요청은 각각 0회다. 검색·설명 품질을 채점한 결과가 아니다. 코드 변경이나 기존 스택 재시작·재배포는 하지 않았다.

## 확인 결과

| 대상 | 읽기 전용 확인 결과 | 판정 |
|---|---|---|
| Ollama | `/api/version` 0.40.13, `/api/tags`의 qwen3:8b digest가 이전 검증 프로필과 일치, `/api/ps`의 로드 모델 없음 | 버전·태그만 일치. 현재 템플릿·토크나이저 전체 동일성 검증은 미실행 |
| Spring | 10월 25일 생성된 `travelmate-server`, 기존 `travel_db` 연결 | 평가 전용 격리 미확인 |
| 실행 JAR | `ConversationController`, `ExactQwenProcess`, `ExecutionObservationFilter`, `PlaceSearchRequest` 클래스 모두 없음 | 최신 도구 루프·가드·관측·독립 검색 경로를 평가할 수 없음 |
| 계산기 설정 | 로컬 Windows 프로필 파일은 존재. 실행 컨테이너에는 정확 계산기 설정·마운트가 없고 해당 클래스도 없음 | 로컬 파일 존재와 서버 적용을 구분. 적용되지 않음 |
| 검색 서버 | 10월 25일 생성된 `travelmate-embedding`, BAAI/bge-m3, rerank `autocast_fp16`, batch 8 | 최신 검색 코드·동결 검색 설정 일치 미검증 |
| 검색 DB | public 테이블이 `place_embeddings`, `place_index_jobs`, `recommendation_requests`, `recommendation_result_outbox`뿐임 | 원문 청크·관계 근거 테이블 없음 |
| corpus | 동결 corpus·Spring 장소·검색 embedding 행이 각각 449개. ID 311·378의 이름·지역·도시·좌표 일치 | 전체 내용·원문·관계·qrels 일치까지 검증한 것은 아님 |

현재 코드가 사용하는 `retrieval_source_versions`, `retrieval_chunks`, `retrieval_chunk_contexts`, `retrieval_chunk_bundles`, `place_active_chunks`, `retrieval_relation_embeddings`는 실행 중인 검색 DB에 없다. 이 상태에서 기존 검색을 호출해도 최신 원문·관계 근거 전달의 연결 검증으로 인정할 수 없다.

기존 `docker` 프로젝트의 Spring DB와 검색 DB를 조회했으며, 모두 `BEGIN READ ONLY` 안에서 `transaction_read_only=on`을 확인했다. 이 DB가 운영 DB라고 단정하지는 않지만, 평가 전용이라는 근거도 없으므로 요청·outbox를 기록하는 검색 API를 보내지 않았다. 테이블 생성·자료 복사·재색인도 하지 않았다.

## 확인 방법과 제한

- Docker 컨테이너 목록 및 inspect에서 이미지 ID·생성일·마운트·필요한 비밀값 제외 설정만 확인했다. 비밀번호·JWT·API 키는 기록하지 않았다.
- JAR 클래스는 `docker exec travelmate-server jar tf /app/app.jar`의 목록에서 검사했다. 최초 `unzip` 시도는 도구 부재와 셸 인용 문제로 실패했으며, 그 결과를 클래스 부재 증거로 사용하지 않았다. 이후 성공한 `jar tf` 결과를 사용했다.
- PostgreSQL의 테이블·컬럼 목록, 행 수, 기준 장소 2건만 읽었다. 449건의 모든 필드·원문·임베딩 해시를 대조하지 않았다.
- Ollama 메타데이터 HTTP 요청은 총 3회다. `/api/chat`, `/api/generate`, 임베딩·검색·리랭킹 요청은 보내지 않았다. 메타데이터의 기본 context 40960은 모델 정보이며 평가 context를 증가시킨 것이 아니다.
- Java 94개·Python 34개는 이전 보고서의 검증 기록이다. 이번 문서 작업에서 테스트를 재실행하거나 실제 연결 통과로 계산하지 않았다.

세부 판정은 [verification.json](verification.json)에 기록했다. 이전 보고서·동결 데이터셋·manifest·로컬 미커밋 수집기는 수정하지 않았다.

## 재개에 필요한 준비

1. 기존 스택을 교체하지 않는 평가 전용 Spring·검색 서버와 분리된 DB·Kafka 토픽을 준비하고, 최신 코드 버전과 대상 DB를 확인한다. 기본 시작 과정의 마이그레이션이나 Kafka 소비가 기존 DB에 영향을 주지 않는지도 확인한다.
2. 검증된 동결 corpus와 사용할 원문·활성 청크·관계 자료의 출처·해시·장소 ID 및 검색 설정을 검증한다. 현재 DB의 449행을 곧바로 일치 판정하지 않는다. 새 수집·모델 호출·유료 enrichment가 필요하면 기존 4문항 실행에 몰래 포함하지 않는다.
3. Windows 검증 프로필을 사용할 수 있는 실행 환경에서 상주 계산기를 설정하고 모델·템플릿·토크나이저 동일성을 재검증한다. Linux 컨테이너에서 검증되지 않은 DLL·경로를 그대로 사용할 수 있다고 가정하지 않는다. 전체 입력＋출력 예약량의 호출별 가드를 유지한다.
4. 평가 서버에 `SEARCH_PLACES`만 허용하고 모델 턴 2·도구 호출 1·실패 시 STOP을 적용한다. 실제 원본 요청·tool_calls·검색 결과·근거·최종 설명·시간·사용량을 기록할 수 있는지 확인한다.

조건 충족 후에도 [기존 실행 범위](../../runtime-qwen-independent-search-v1/20261102-01/execution-scope-proposal.json)를 유지한다. `PLR-TM-palaces-01/03/04`, `PLR-TM-family_parks-04`의 각 1회, 동시성 1, 재시도 0, Qwen 최대 8회·검색 최대 4회다. 계획 Job·추가 계획 LLM·GPT·judge·유료 호출은 0회다. 한도·동일성·예산·도구·검색·인용·관측·corpus 조건의 첫 실패에서 배치를 중단한다.

실제 지연·사용량·순위·설명 적합성은 아직 미관측이다. 설정이 없는 상태를 성공으로 바꾸거나, 결과를 얻기 위해 context를 늘리거나 원문을 절단하지 않았다.
