# TravelMate 평가 데이터 버전 관리

현재 Agent 평가 버전은 [V1.4.0](V1.4.0/README.md)입니다.
`Evaluation/V1.4.0/` 아래 common에 공통 원본과 타입별 생성 뷰를 두고,
plannerLLM·managerLLM에 같은 대화·제어 LLM의 기능별 평가를 각각 100문항씩 관리합니다.
일정 생성·수정은 이 LLM의 도구입니다. [도구 중심 평가 명세](V1.4.0/TOOL_EVALUATION.md)는
도구 선택·인자, 실행 결과, 최종 응답을 구분해 골든셋과 채점기를 연결합니다.
기존 v1.3.0의 사람 판정·참조 답변·실행 결과는 그대로 보존합니다.
새 데이터셋의 기대 응답 타입은 PLACES, PLAN, PLAN_DIFF, CLARIFICATION, TEXT이며,
한 문항이 검색·도구·계획·상태·대화 등 여러 평가 트랙에 속할 수 있습니다.

기존 장소 검색 자료는 `Evaluation/<버전>/`에 보관하며 그 기준 버전은 **v1.3.0**입니다. 사용자의 확인에 따라 기존 100문항·273행의 사람 검수 완료를 기록했습니다. 새 Agent 평가는 위의 **V1.4.0**에서 타입·기능별로 관리합니다. 이전 버전의 검수 상태는 당시 기록으로 보존합니다. 검수 완료는 전체 검색·생성·Ragas 성능 평가 완료와 별개입니다.

```text
Evaluation/
├── README.md
├── v1.1.0/                         # 초기 수정본
│   ├── cases.source.json
│   ├── golden.jsonl
│   ├── review.csv
│   └── ...
├── v1.2.0/                         # 판정 13건 추가
│   ├── cases.source.json
│   ├── golden.jsonl
│   ├── review.csv
│   └── ...
└── v1.3.0/                         # 현재 검토 기준
    ├── cases.source.json           # 작성 원본
    ├── golden.jsonl                # 원본에서 생성한 100문항
    ├── review.csv                  # 원본에서 생성한 검수표
    ├── review_notes_filled_v1.3.0.csv # 사용자가 검토할 메모 273행
    ├── review_notes_by_question.md # 들여쓰기한 질문별 설명
    ├── evaluation_review_criteria.md
    ├── manifest.json
    ├── validation.json
    ├── snapshot.json
    ├── corpus.json
    ├── build_dataset.py
    ├── run.sh
    └── tests/
```

## 버전별 자료

| 버전 | 문항 | 장소별 판정 | 검수표 행 | 변경 내용 |
|---|---:|---:|---:|---|
| [v1.1.0](v1.1.0/README.md) | 100 | 237 | 257 | 필수 조건 판정·직접 인용·검증기 보완 |
| [v1.2.0](v1.2.0/README.md) | 100 | 250 | 270 | 개발 문항 판정 13건 추가 |
| [v1.3.0](v1.3.0/README.md) | 100 | 253 | 273 | 질문 4개 정정·질문 그룹 기준 분할·리뷰 메모 보완 |

검수표 행 수에는 장소별 판정 외에 답변 불가·확인 질문 20문항이 포함됩니다. 각 폴더는 동일한 관광 데이터 스냅샷과 해당 버전의 작성 원본·빌더·산출물·문서를 함께 보관합니다. 스냅샷 바이트와 기존 정답 판정은 폴더 정리 과정에서 변경하지 않았습니다.

## 지금 읽거나 작성할 파일

- [질문별 리뷰 설명](v1.3.0/review_notes_by_question.md)
- [리뷰 메모가 채워진 CSV](v1.3.0/review_notes_filled_v1.3.0.csv)
- [평가 기준](v1.3.0/evaluation_review_criteria.md)

기존 `develop`의 `evaluations/place_search/review.csv`는 v1.3.0 리뷰 메모 273행이었지만 작성 원본·manifest는 v1.1.0이었습니다. 이 검수표를 `v1.3.0/review_notes_filled_v1.3.0.csv`에 바이트 단위로 보존하고, 각 버전의 `review.csv`는 해당 버전 작성 원본과 일치하도록 정리했습니다. 기존 `develop`의 리뷰 내용은 누락하지 않았습니다.

`review.csv`는 생성 파일입니다. 사용자가 작성하는 메모는 별도 `review_notes_filled_v1.3.0.csv`에 보관하면 빌드할 때 덮어쓰지 않습니다. 메모를 작성 원본으로 자동 가져오지는 않습니다.

## 실행

저장소 루트에서 Docker Desktop과 Git Bash로 실행할 수 있습니다.

```bash
bash Evaluation/v1.3.0/run.sh --check
bash Evaluation/v1.3.0/run.sh --test
```

다른 버전을 검증하려면 경로의 버전만 바꾸세요. 호스트 Python이 있다면 다음과 같이 실행할 수 있습니다.

```bash
python -X utf8 Evaluation/v1.3.0/build_dataset.py --check
python -m unittest discover -s Evaluation/v1.3.0/tests -v
```

이전 `bash evaluations/place_search/run.sh --check` 명령은 v1.3.0으로 연결합니다. 버전을 고정한 실험에는 위의 명시적인 버전 경로를 사용하세요.

## 다음 버전을 만들 때

1. 기준 폴더를 새 버전 폴더로 복사하고 해당 버전의 작성 원본을 수정합니다.
2. `cases.source.json`의 `dataset_version`을 새 버전에 맞춥니다. 빌더에 이전 버전 전용 검증이 있다면 함께 확인합니다.
3. `bash Evaluation/<새 버전>/run.sh --build`로 산출물을 생성하고 `--check`, `--test`를 실행합니다. 작성 중인 메모는 생성 파일과 구분해 보관합니다.
4. 변경 이력·버전별 README·이 목록을 갱신합니다. 새 폴더에서는 이전 버전 변경 CSV와 중복 발췌본을 제거하고, 이전 기록은 해당 버전 폴더에 보존합니다.

v1.3.0 빌더의 일반 재생성은 기존 실행 결과를 보존합니다. 실행 결과가 있는 폴더를 새 버전으로 복사해 질문·조건·스냅샷 등을 바꾸었다면, 새 폴더에서 이전 실행을 초기화하려는 경우에만 `--build --reset-runtime`을 명시하세요. 참조 답변만 갱신할 때는 일반 `--build`로 충분합니다.

리뷰 메모를 옮길 때는 행 번호 대신 `case_id + place_id`로 연결하고, 질문·조건·판정이 바뀐 항목은 다시 검토합니다. 자동 검증 통과와 AI 초안 작성을 사람 검수 완료로 기록하지 않습니다.
