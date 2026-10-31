# TravelMate 평가

대화·제어 LLM 하나가 장소 검색·일정 생성·수정·기억 조회 도구를 호출한다.
데이터와 채점 기준은 버전별로, 코드는 공통/트랙별로, 실행 결과는 실행별로 관리한다.

```text
Evaluation/
├── requirements/                  # 기본·선택 의존성
├── datasets/
│   ├── v1.1.0/ · v1.2.0/ · v1.3.0/ # 과거 버전의 동결 원본
│   └── v1.4.0/
│       ├── source/                # 수정하는 문항·기억/페르소나 조건·검수 기록
│       ├── generated/             # 생성 골든셋·분할·타입/트랙별 뷰·스키마
│       ├── rubrics/               # 버전별 GPT 기준
│       └── manifest.json · validation.json
├── common/
│   ├── dataset/                   # 빌더·검증·계약·입출력
│   ├── metrics/                   # 검색·기억 공용 순위 계산
│   ├── judge/                     # GPT·구조화 출력·근거 인용 검사
│   ├── runs/                      # 기록 채점 실행기·실행 이력
│   └── observability/             # 관측 연동의 현재 범위 안내
├── tracks/
│   ├── search/ · tool_call/ · plan/ · state/
│   ├── memory/ · behavior/ · persona/ · message/
│   └── end_to_end/
├── runs/<트랙>/<버전>/<실행ID>/     # 실제 실행 후 생성
└── tests/                         # 채점 코드·이동 보존·실행 경로 검증
```

현재 데이터는 [v1.4.0](datasets/v1.4.0/README.md)의 **200문항**이다.
[도구 중심 평가 명세](datasets/v1.4.0/TOOL_EVALUATION.md),
[경로 이동표와 보존 정책](MIGRATION.md), [트랙별 구현 상태](tracks/README.md)를 참고한다.
보존 v1_local·v2 문맥 응답의 소규모 검색 진단은 [실행 방법](tracks/contextual/README.md)과
[2026-10-31 실측 보고서](runs/contextual/stored-nine-pairs/20261031-01/REPORT.md)를 참고한다.
[문제 정의와 해결 실험안](tracks/contextual/PROBLEMS_AND_SOLUTIONS.md)에 남은 오류와 개선안·평가 기준을 기록했다.
[장소별 근거 1·2·3개 비교](runs/contextual/multi-evidence-v1/20261031-01/REPORT.md)에 실험 A의 구현·실측·보존 기록을 추가했다.
기존 100+100 묶음은 generated/by_group에 조회용으로 보존한다. 두 LLM을 뜻하지 않는다.
기억·페르소나 시나리오는 source/cases.source.json의 해당 문항에 포함된다.
같은 정답을 별도 source 파일에 중복 작성하지 않는다.

## 실행

저장소 루트 PowerShell 기준. --split은 평가자가 직접 지정한다.

```powershell
.\.venv-ragas\Scripts\python.exe -m pip install -r Evaluation/requirements/base.txt
.\.venv-ragas\Scripts\python.exe Evaluation/common/dataset/validate.py
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/search/run.py check
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/tool_call/run.py check
```

원본을 수정한 뒤에만 생성물을 다시 만든다. 실행 결과는 건드리지 않는다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/common/dataset/build.py --build
```

입력을 내보내고 **별도 수집기가** 실제 Agent/API를 실행해 응답을 기록한다.
내보낸 model_input만 LLM에 전달하고 harness_fixtures는 도구 테스트 실행기만 읽는다.
기대값·reference·사람 점수는 모델 입력에 들어가지 않는다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/search/run.py export-inputs --split development --output search_inputs.jsonl
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/search/run.py evaluate --split development --responses embedding_records.jsonl
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/search/run.py evaluate --split development --responses reranked_records.jsonl
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/tool_call/run.py evaluate --split development --responses agent_records.jsonl
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/persona/run.py evaluate --split development --responses agent_records.jsonl --judge --env-file .env
```

위 파일명은 사용 예시이며 실제 측정 결과를 미리 넣은 것이 아니다.

--type PLACES/PLAN/PLAN_DIFF/CLARIFICATION/TEXT로 기대 응답 타입을 지정할 수 있다.
--track은 평가 문항을 추가로 좁힌다. --group plannerLLM/managerLLM은 이동 전 문항 묶음의
선택 필터이며 모델 선택이 아니다. 지정하지 않으면 해당 트랙의 모든 문항에서 선택한다.
--dataset Evaluation/datasets/v1.4.0으로 데이터셋을 명시할 수 있다.

--judge가 없으면 OpenAI를 호출하지 않는다. 검색·리랭킹 순위 평가에는 문장형 reference가 필요 없다.
GPT는 .env의 OPENAI_API_KEY를 읽으며 기존 설정인 gpt-4.1-mini로 발화를 평가한다.
이번 이동에서 모델·문항·점수 기준을 변경하지 않았다. Ragas 내장 지표와는 구분한다.

결과는 새로운 runs/<트랙>/v1.4.0/<실행ID>/에 쓴다. 기존 결과 디렉터리는 덮어쓰지 않는다.
run.json에 Git SHA·데이터/페르소나 해시·명시한 범위를, outputs/에 채점 입력,
scores/에 채점 결과를 기록한다. summary.json은 평균과 평가 건수, latest.json은 최신 실행 참조다.
실제 API 호출·여러 턴 재생·지연 p50/p95·V1.4용 LangSmith 자동 게시는 아직 미구현이다.

## 이전 버전

v1.1.0~v1.3.0은 파일 내용을 바꾸지 않고 datasets/로 옮긴 읽기용 아카이브다.
과거 실측 파일도 함께 동결하며 새 runs/에 새로운 측정인 것처럼 등록하지 않는다.
아카이브 안의 옛 명령과 source_dataset 경로는 당시 기록으로 보존한다.
기존 검사는 새 위치에서 실행할 수 있다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/datasets/v1.3.0/build_dataset.py --check
.\.venv-ragas\Scripts\python.exe -m unittest discover -s Evaluation/datasets/v1.3.0/tests -v
.\.venv-ragas\Scripts\python.exe -m unittest discover -s Evaluation/tests -v
```

과거 평가의 환경변수를 확인할 때는 --env-file .env를 명시한다.
아카이브에 쓰는 평가 실행은 피하고, 새 평가에는 tracks/의 실행기를 사용한다.
