# 실제 평가 실행 결과

[OpenAI strict 기존 2문항 검색 도구 연결 검증 완료](contextual/openai-strict-search-two-case-v1/20261103-01/REPORT.md)는
문항별 1회 관찰과 category 선택·적용 필터·검색 결과·설명·시간·비용 기록이다.
검색어 확장과 일부 정식 인용 부족은 미해결 개선 후보로 남겼다. 전체 호출 신뢰성·평균 성능·p95·8개 분류·일정 생성·수정 검증을 뜻하지 않는다.

검색 수집기의 `attempts.jsonl`은 전송 전 예약과 원본 요청·응답을 기록한다.
MOCK·failed·not_run은 실제 성공·지연·품질 집계와 구분한다.
[검색 평가 도구 계약](../tracks/search/README.md)을 참고한다. 과거 기록과 동결 자료는 덮어쓰지 않는다.

[동일 Qwen 입력 정확 계산과 검색 계약 제안](contextual/exact-qwen-and-search-contract-v1/20261102-01/REPORT.md)은
추론을 보류한 오프라인 검증이며 기존 가드는 변경하지 않았다.

[모델 평가 준비 기록](contextual/model-evaluation-preparation-v1/20261101-01/REPORT.md)은
메타데이터 조사·오프라인 예산·모의 검증이며 실제 추론 결과와 구분한다.

새 실행은 트랙/데이터셋 버전/고유 실행ID 아래에 쓴다. 기존 경로는 덮어쓰지 않는다.

```text
runs/search/v1.4.0/
├── latest.json
└── <run_id>/
    ├── run.json             # 평가 코드 Git SHA·범위·데이터/페르소나 해시
    ├── precheck.json        # 응답·입력 해시·GPT 설정 확인
    ├── outputs/records.jsonl # 실제 채점 입력 보존
    ├── scores/results.jsonl  # 문항별 코드/GPT 점수
    └── summary.json         # 평균·평가 건수·누락·타입별 집계
```

run.json의 latency_measurement는 현재 not_collected_by_this_runner다.
실제 API 수집을 구현하기 전에는 p50/p95를 가상 값으로 채우지 않는다.
--precheck-only는 GPT 호출과 실제 점수 산출을 하지 않으며 latest.json을 바꾸지 않는다.
명시적 --output-dir도 데이터셋 내부나 기존 경로이면 거부한다.
이 저장소에 예시를 실측으로 보이게 하는 가짜 점수를 넣지 않는다.

[토큰 예산·서버 실행 관측 모의 검증](contextual/token-budget-observation-v1/20261101-01/REPORT.md)은
실제 모델 평가와 구분해 보존한다. MOCK 실행의 품질 항목은 채점하지 않는다.

[Qwen 정확 가드·계획 없는 검색 구현](contextual/runtime-qwen-independent-search-v1/20261102-01/REPORT.md)은
모의 회귀와 저장 메타데이터의 오프라인 토큰 검증이다. 실제 모델·검색 평가를 실행하지 않았다.

[Qwen 계산기 상주·재사용](contextual/resident-qwen-counter-v1/20261102-01/REPORT.md)은
초기화·반복 계산을 분리 측정하고 기존 토큰 ID 일치를 검증한 기록이다. 실제 추론은 계속 보류한다.
