# 장소별 공통 청크 검색 구조

[계획](../plans/contextual-retrieval.md) · [상세 명세·DB 이행](../specifications/contextual-retrieval.md)

```mermaid
flowchart TD
    Tour[Spring TourAPI 원본 이벤트] --> Worker[기존 Kafka 인덱싱 작업자]
    Web[Perplexity web_search·fetch_url] --> Raw[보존 원문·도구 응답]
    Accounts[확보한 블로그·리뷰 본문] --> Raw
    Raw --> Sources[공통 SourceDocument와 내용 버전]
    Sources --> Split[원문 offset 기반 분할]
    Split --> Agent[Perplexity Agent<br/>버전별 문맥·장소 역할 생성]
    Version[v1 보존 / v2 기본] --> Agent
    Baseline[기존 record 비교 실행<br/>원문·분할·모델 설정 고정] --> Agent
    Agent --> Validate[원문 ID·offset·장소 ID·역할 검증]
    Validate --> Unattributed[귀속 불명확: 두 배열 비움<br/>응답 보존·색인 제외]
    Validate --> Bundle[불변 번들 저장과 재색인 등록]
    Bundle --> Worker
    Worker --> Archive[LocationReview/place_id_장소명<br/>원문·응답·후보 청크 보존]
    Worker --> Select[subject만 선택<br/>출처 분산·중복 제거·최대 20]
    Select --> Embed[기존 BGE-M3<br/>짧은 문맥 + 원문]
    Embed --> CAS[원본 버전·보강 스냅샷·chunk_generation 확인]
    CAS --> Active[(FastAPI DB<br/>장소별 활성 슬롯 1..20)]
    Query[사용자 질의] --> QEmbed[기존 BGE-M3]
    QEmbed --> Retrieve[활성 청크 벡터 검색<br/>장소별 최고 근거 1개·점수 합산 없음]
    Active --> Retrieve
    Retrieve --> Rerank[기존 BGE reranker<br/>선택된 문맥 + 원문]
    Rerank --> Result[Kafka 완료 payload<br/>장소 상세 + evidence_chunks]
    Result --> Spring[Spring 결과 저장·앱 응답]
```

```mermaid
erDiagram
    retrieval_source_versions ||--o{ retrieval_chunks : preserves
    retrieval_chunks ||--o{ retrieval_chunk_contexts : contextualizes
    retrieval_chunk_contexts ||--o{ place_active_chunks : indexes
    place_embeddings ||--o{ place_active_chunks : subject_slots
    place_embeddings ||--o{ retrieval_chunk_bundles : imports
```

청크는 전역 UUID이고 장소와 N:M 관계다. `place_refs`는 원문 청크의 subject/view_target/mentioned를 보존하며,
실제 검색 연결인 place_active_chunks에는 subject만 들어간다. 청담도로공원의 벤치에서 청담대교가 보이는
후기가 있을 때 공원의 시설을 대교의 시설로 색인하지 않는다. 여러 subject를 실제로 다루는 청크는
각 장소의 20개 제한에 각각 포함된다.

생성·수집은 오프라인 관리 작업이며 추천 요청은 Perplexity를 호출하지 않는다.
DB 트랜잭션은 네트워크 호출·모델 추론 동안 잡지 않는다. 활성 집합은 추론 뒤 최신 세대를 확인하고 원자 교체한다.
Spring DB와 FastAPI DB 사이 JOIN/FK는 없다. 새 FK는 FastAPI 검색 DB 내부에만 존재한다.
기존 무청크 장소는 호환 벡터로 조회할 수 있으므로 단계별 재색인이 가능하다.
v2에서도 같은 문서의 다른 구간은 장소 식별이나 필요한 배경에 활용한다. 청크 밖 정보 전체를 금지하지 않는다.
baseline 비교는 모델/프리셋 선택까지 고정하지만 공급자가 반환한 실제 모델도 별도로 비교해 기록한다.
검증기의 형식/역할 일치 확인만으로 장소 귀속·문맥의 의미 정확성이나 실제 품질 향상을 보증하지 않는다.
