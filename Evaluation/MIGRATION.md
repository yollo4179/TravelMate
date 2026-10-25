# 평가 디렉터리 이동표

2026-10-26 기준 데이터·공통 코드·트랙 코드·결과를 분리했다. 제품 LLM은 하나다.
파일 이동은 문항·판정·검수 상태·모델·관련도 임계값을 변경하지 않는다.

| 이전 | 현재 |
|---|---|
| Evaluation/v1.1.0, v1.2.0, v1.3.0 | Evaluation/datasets/동일버전 (전체 파일 바이트 보존) |
| V1.4.0/common/cases.source.json | datasets/v1.4.0/source/cases.source.json |
| V1.4.0/common/corpus.json | source/corpus.source.json 및 generated/corpus.json |
| V1.4.0/common/snapshot.json | datasets/v1.4.0/source/snapshot.json |
| V1.4.0/common/source_goldenset_v1.3.0.jsonl | datasets/v1.4.0/source/동일파일 |
| V1.4.0/common/source_review_notes.csv | datasets/v1.4.0/source/review_notes.csv |
| V1.4.0/common/persona, judge_config.json | datasets/v1.4.0/source/ |
| V1.4.0/common/*.schema.json, tool_contracts.json | datasets/v1.4.0/generated/schemas/ |
| V1.4.0/common/golden.jsonl, development.jsonl, test.jsonl, by_type, by_track | datasets/v1.4.0/generated/ |
| V1.4.0/plannerLLM, managerLLM의 골든셋 | datasets/v1.4.0/generated/by_group/ |
| V1.4.0/plannerLLM/rubric.md, managerLLM/rubric.md | datasets/v1.4.0/rubrics/plan_quality.md, behavior.md |
| V1.4.0/common/build_dataset.py, storage.py, contracts.py, seed_cases.py | common/dataset/ |
| V1.4.0/common/metrics.py | common/metrics/ranking.py 및 tracks/별 채점 모듈 |
| V1.4.0/common/judge.py | common/judge/의 실행·설정·구조화 출력·인용 검사 |
| V1.4.0/common/runner.py | common/runs/runner.py와 tracks/*/run.py |
| V1.4.0/common/routing.py | tracks/plan/score_route.py |
| V1.4.0/common/tests | tests/ |
| V1.4.0/common/requirements.txt | requirements/base.txt |
| V1.4.0/*/results (존재하는 경우) | runs/imported/v1.4.0/기존묶음 |
| 새 평가 결과 | runs/트랙/버전/실행ID/ |

V1.4.0의 cases.source.json과 기존 golden JSONL의 바이트·ID·기대값을 유지했다.
따라서 같은 모델 입력·도구 픽스처로 내보낸 input_sha256도 유지된다.
현재 명령은 --dataset, 명시적인 --split과 트랙별 run.py를 사용한다.

과거 버전은 당시 코드·실측·설명까지 원형으로 보관하는 예외다.
아카이브 내부의 옛 절대/상대 표시 경로는 이력이며 새 실행 경로로 간주하지 않는다.
새 v1.4.0 실행 결과만 분리된 runs/에 쓴다. 과거 실측을 재실행된 결과로 위장하지 않는다.
기존 evaluations/place_search/run.sh는 새 아카이브 위치의 검사 스크립트로 연결했다.

Ragas ID·검색 후보별 GPT 판정·LangSmith 게시·API 수집을 이 이동에서 새로 구현하지 않았다.
기존 v1.3.0 코드는 동결 아카이브에서 확인할 수 있다. 구현 상태는 tracks/README.md에 적었다.
