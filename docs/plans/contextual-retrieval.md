# 장소 청크 기반 Contextual Retrieval 구현 계획과 완료 범위

기준: develop의 기존 장소 보강 구현(`1c822db`). 기존 FastAPI DB·Kafka 작업자·BGE-M3·BGE reranker를 확장한다.

## 요구사항과 구현

| 요구사항 | 구현 위치·판정 |
|---|---|
| 장소당 활성 검색 청크 ≤20 | `select_active`, DB `place_active_chunks.slot` 1..20 + 장소별 slot PK |
| 원문과 탈락 청크 보존 | `retrieval_source_versions`, `retrieval_chunks`, 파일 아카이브. 선정 탈락 때문에 삭제하지 않음 |
| TourAPI·블로그·리뷰 공통 형식 | `app/contextual/contracts.py`, 소스 전략 레지스트리 |
| 원문/문맥 분리, 함께 임베딩 | `SearchChunk.chunk_text`, `context_text`, `embedding_text` |
| 전역 ID·재수집 멱등성 | source UUIDv5 + 내용 버전 + span + splitter 버전 기반 chunk UUIDv5 |
| 대상/전망/단순 언급 구분 | `subject`, `view_target`, `mentioned`; DB trigger도 subject만 활성화 허용 |
| 생성 모델·프롬프트·출처·인용 위치 | context revision JSON, source version JSON, 원문 Unicode offset |
| Perplexity 문맥 생성 | 별도 offline CLI, 기본 Agent `sonar-pro`, 모델/프리셋 교체 가능 |
| 프롬프트 버전과 비교 | `prompts/v1_*.py`, `v2_*.py`; 기존 기록은 기록된 버전으로 검증, `--baseline-record`로 입력/설정 고정 |
| 로컬 실행 재사용 | `profiles/v1_local_2d365e87c12314cb.json`; 9개 보존 실행을 명시적으로 읽고 원문·effort·출력 한도·스키마 고정, 지시문만 교체 |
| 기존 검색 경로 연결 | Kafka 인덱싱 → 청크별 벡터 → 장소별 최고 근거 1개 → 기존 리랭커 |
| 추적 파일 | `LocationReview/<place_id>_<장소명>/` |
| 검색 DB 변경 | `Docker/search-init/03-contextual-chunks.sql`, runtime 멱등 적용 |

## 순서

1. 별도 검색 DB를 백업하고 additive 스키마 적용. 기존 장소 행과 벡터는 유지한다.
2. 새 작업자는 기존 TourAPI 설명도 공통 청크로 분할한다. 원래 Agent 보강 스냅샷의 인용문도 공통 형식으로 이전한다.
3. 블로그/리뷰 원문 입력 또는 기존 수집 record에서 Perplexity로 짧은 문맥을 생성한다. 실제 확보 범위만 기록한다.
4. 적용은 전체 원문과 모든 청크를 보존하고 재색인 작업을 등록한다. 생성/수집은 온라인 검색 요청에서 호출하지 않는다.
5. 임베딩 계산 후 원본 버전·보강 스냅샷·chunk_generation을 비교하고 장소 행/활성 슬롯/작업 상태를 원자 갱신한다.
6. 청크 없는 기존 행은 기존 벡터로 조회 가능하다. 기존 장소는 변경 이벤트 재발행 또는 명세의 재색인 SQL로 점진 이전한다.

## 선택 정책과 제한

20은 **활성 색인 개수**이며 검색 Top-K나 반환 장소 수가 아니다. 부족하면 채우지 않는다.
같은 원문 텍스트는 한 슬롯만 사용하고 출처별 round-robin으로 자료 편중을 줄인다.
조건이나 상충된 원문을 한 문장으로 합치지 않는다. 이 선택기는 원문 조건의 의미적 중요도를 자동 판정하는 모델은 아니다.
20개보다 많은 근거에서 모든 조건을 보장하는 최적 선택, BM25/RRF, 가상 질문 별도 벡터는 후속 평가 대상이다.
현재 질문 예시는 저장만 하며 원문 대신 추천 근거로 사용하지 않는다.
새 기본 프롬프트 v2는 예상 질문을 생성하지 않는다. 같은 문서에서 필요한 배경은 허용하되 현재 구간의 주제를 유지하고,
귀속이 불명확하면 place_refs와 entities를 모두 비워 원본 응답에만 보존한다. v1 원문·기록·기존 질문은 그대로 읽는다.
별도 semantic-review 파일의 표시를 적용하는 기능이나 복수 청크 리랭킹은 이번 프롬프트 버전 변경에 포함하지 않는다.

## 검증과 출시 판정

모의 Agent HTTP 응답으로 요청 형식·offset 변조·알 수 없는 장소·캐시·429 무재시도·원문 보존을 검증한다.
격리된 PostgreSQL에서 20개 제한, 언급 장소 활성화 거부, 원문/문맥 버전, 재적용 멱등성,
재색인과 장소별 검색, 추론 중 최신 문맥 적용 시 오래된 작업 거부를 확인한다.
실제 API 키가 없는 환경에서는 Perplexity 과금 호출·계정 모델 지원·생성 품질을 검증 완료라고 표시하지 않는다.
기존 평가셋을 생성 질문으로 덮어쓰지 않는다. 검색 품질 향상이나 기존 리랭커의 속도 목표 달성은 별도 측정 전 주장하지 않는다.

로컬 비교 호환 검증에서는 원본 36개 파일의 해시와 9개 요청/응답을 확인하고 v2 미리보기 9개를 생성했다.
기존 실행은 재호출하지 않는다. 새 v2 응답의 장소/시설 귀속·주제·날짜/조건 보존·불필요한 제외를 검수한 뒤
동일 질의와 원문 집합으로 재색인/검색 비교를 진행한다. 호환 검증 통과를 생성 품질 개선으로 간주하지 않는다.
