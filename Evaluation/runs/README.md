# 실제 평가 실행 결과

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
