# 관측 연동 상태

V1.4 기록 채점기는 run.json·outputs·scores·summary를 로컬에 저장한다.
`langsmith_transport.py`는 명시적 조회/게시 설정과 HTTP 요청별 상한을 적용한다.
직접 검색 기록은 `search_records.py`에서 실패·미실행·MOCK·미확인 자료를 구분한다.
과거 구현은 ../../datasets/v1.3.0/ragas_support/langsmith_observability.py에 동결 보존한다.
자세한 구현 상태는 ../../tracks/README.md를 참고한다.

Spring의 요청·모델·도구·Job 관측을 기존 입력 해시와 연결하는
[토큰 예산·실행 기록 구조](../../../docs/architecture/token-budget-and-execution-observations.md)를 추가했다.
`tracks/tool_call/convert_server_trace.py`는 기존 export와 명시적 요청 바인딩을 요구한다.
`server_trace.py`는 native MOCK와 미관측 품질 항목을 채점 분모에서 제외한다.
서버 artifact 동일성 검사와 실제 검색·계획 품질 평가는 별개다.
관측 변환·채점은 외부 관측 서비스에 자동 게시하지 않는다.
조회·집계·수동 게시 도구는 [검색 도구 계약](../../tracks/search/README.md)을 따른다.
