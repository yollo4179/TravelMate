# TravelMate 장소 검색 평가셋 v1.3.0

서울 관광지 449건과 TourAPI 원본 449건의 스냅샷을 기준으로 만든 질문 100개입니다. 현재 버전의 작성 원본·산출물·검수 자료를 함께 관리합니다.

**상태: AI의 원문 대조·구조 검증 완료 / 사람 검수 대기.** 검색·LLM 실행이나 RAGAS 성능 측정은 수행하지 않았습니다.

## 먼저 사용할 파일

- **검수할 리뷰:** [review_notes_filled_v1.3.0.csv](review_notes_filled_v1.3.0.csv)
- **읽기 쉬운 리뷰:** [review_notes_by_question.md](review_notes_by_question.md)
- **평가용 정답:** [golden.jsonl](golden.jsonl)
- **정답·점수 수정 원본:** [cases.source.json](cases.source.json)
- **관광지 원문:** [corpus.json](corpus.json)

v1.3.0에서는 문항 4개의 판정을 정정하고, 질문 그룹은 분리하되 같은 장소가 두 분할에 나오는 것은 허용했습니다. 현재 변경 내용은 [CHANGELOG.md](CHANGELOG.md)와 [changes_1.3.0.csv](changes_1.3.0.csv)를 보세요. 이전 변경 기록은 [v1.1.0](../v1.1.0/README.md)·[v1.2.0](../v1.2.0/README.md)에 보관합니다.

## 로컬 실행

호스트 Python 설치 없이 Docker Desktop과 Git Bash에서 확인할 수 있습니다. 저장소 루트에서:

```bash
bash Evaluation/v1.3.0/run.sh --check
bash Evaluation/v1.3.0/run.sh --test
```

ZIP을 따로 풀었다면 `Evaluation/v1.3.0` 폴더 안에서 `bash run.sh --check`로 실행해도 됩니다. `--check`와 `--test`는 데이터셋 폴더를 읽기 전용으로 마운트합니다. Windows 경로는 `cygpath`로 변환합니다. 실제 Windows PC에서의 실행 검증은 별도이며, Linux Docker에서는 검증했습니다.

작성 원본을 변경한 뒤 재생성하려면:

```bash
bash Evaluation/v1.3.0/run.sh --build
```

**재생성은 review.csv를 포함한 파생 산출물을 덮어씁니다.** 작성한 검수 메모는 별도로 보존하고 필요한 판정/검수 이력을 `cases.source.json`에 반영한 뒤 버전을 올리세요. CSV 메모를 작성 원본으로 자동 가져오지는 않습니다.

Python 3.10 이상을 사용할 수 있다면:

```bash
python -X utf8 Evaluation/v1.3.0/build_dataset.py --check
python -m unittest discover -s Evaluation/v1.3.0/tests -v
```

표준 라이브러리만 사용합니다. DB·네트워크·모델 호출은 없습니다. Docker 사용 시에는 도구용 Python 이미지를 최초에 받을 수 있습니다.

## 파일

| 파일 | 용도 |
|---|---|
| `snapshot.json` | 업로드된 places·TourAPI 원본 전체, 바이트 보존 |
| `corpus.json`, `places.csv` | 관광지 449건과 설명·메타데이터 |
| `cases.source.json` | 질문·관련도·인용 anchor·필수 조건 판정의 작성 원본 |
| `golden.jsonl` | 문항 100개 전체 |
| `development.jsonl`, `test.jsonl` | 개발 80개 / 시험 20개 |
| `search_api.jsonl` | 기본 장소 검색 API에 연결할 60개 |
| `context_search.jsonl` | 대화·장소 제외·반경 처리가 필요한 20개 |
| `answer_behavior.jsonl` | 근거 부족·추가 질문 행동을 확인할 20개 |
| `review.csv` | 질문·조건·관련도·인용을 함께 확인하는 검수표 |
| `manifest.json`, `validation.json` | 버전·분포·파일 해시·검증 결과 |
| `CHANGELOG.md`, `changes_1.3.0.csv` | 현재 v1.3.0의 변경 내용 |
| `build_dataset.py`, `tests/` | 생성·검증·회귀 테스트 |

## 관련도 판정

- **3점:** 질문의 핵심 의도와 명시 필수 조건을 직접 충족합니다.
- **2점:** 필수 조건을 근거로 확인할 수 있으나 직접성·시설 범위가 낮은 유용한 대안입니다. 동일 시설의 상위 공간은 다른 인용에서 위치 관계와 기능을 확인할 수 있어야 합니다.
- **1점:** 주제만 일부 관련되거나 필수 조건의 근거가 부족합니다. 정답으로 집계하지 않습니다.
- **0점:** 의도가 다르거나 명시 조건을 위반합니다.

`relevant_place_ids`는 2점 이상, `strict_relevant_place_ids`는 3점만 담습니다. 전자는 관련 대안까지 허용하는 지표, 후자는 직접 정답 중심의 지표에 사용할 수 있습니다. 둘을 같은 지표로 혼용하지 않습니다.

문제가 있었던 네 문항은 `semantic_constraints`에 필수 조건을, 각 판정의 `semantic_constraint_support`에 근거 지지 여부를 기록했습니다. 미확인 후보가 2점 이상으로 올라가면 검증기가 거부합니다. 이 검사는 **작성한 주석의 일관성**을 확인하며 문장의 의미를 자동으로 증명하는 기능은 아닙니다.

화랑대 철도공원과 그 안의 노원 불빛정원은 같은 장소 범위가 겹치는 사례입니다. 상위 공간을 대안으로 인정한 2점은 유지하며, `supporting_place_ids`와 같은 문항의 인용에서 근거 관계를 확인할 수 있습니다.

## 검증 범위

- 실제 ID·장소명·TourAPI ID·인용 문자열·문자 범위·JSON 위치·수집일 일치
- 양성의 지역·도시·반경·제외 조건, 전체 후보 수 재계산
- `relevant_place_ids`와 관련도 threshold 집합 일치
- 질문·유사 의도 그룹(group_id) 단위의 개발/시험 분리. 같은 장소의 분할 간 재사용은 허용
- 작성 원본 재생성 결과와 골든셋 일치
- corpus·검수 CSV·분할/평가 트랙 파일·manifest·validation 일치
- 정답 후보 4개·DJ박스 인용·추가 한옥마을·검증 실패 입력에 대한 회귀 검사

스냅샷 SHA-256은 다음과 같이 유지됩니다.

```text
410a9c3c46004cb30644455fe9d5ddb01a52a04a700ffe04159605cf94661218
```

`.gitattributes`의 `snapshot.json -text`는 Git이 스냅샷의 줄바꿈을 바꾸지 않게 합니다. 생성 파일은 LF로 저장하며, 해시는 그 바이트를 기준으로 계산합니다.

## 남아 있는 한계

**사람 검수는 완료되지 않았습니다.** 수정 이력에 AI 검토임을 기록하고 100개 모두 `pending_human_review`를 유지합니다. 사람이 확인했다면 실제 검수자·시각을 작성 원본에 기록합니다.

**부분 관련도 판정입니다.** 현재 질문–장소 판정은 253개, 판정한 장소는 72개입니다. 449건 전부에 대해 질문별 관련도를 판정한 것은 아닙니다. 남산골한옥마을을 보완했어도 다른 미판정 정답이 있을 수 있습니다. 키워드·dense·rerank의 상위 후보를 합쳐 추가 검수하고, `judged@K`와 미판정 처리 정책을 보고하세요. 미판정 후보를 자동 0점으로 두지 않습니다. Recall도 판정된 정답 집합을 기준으로 한 값임을 명시합니다.

**API와 평가 범위가 다릅니다.** `GET /api/places/search`의 질문·지역·도시·분류 입력으로는 `search_api.jsonl`을 평가합니다. 제외·대화·반경 입력을 처리하는 상위 흐름에는 `context_search.jsonl`을, 기권/추가 질문을 처리하는 대화 흐름에는 `answer_behavior.jsonl`을 연결합니다. 자연어 조건 추출까지 평가하려는 실험에서 정규화한 조건을 시스템에 미리 넣으면 그 단계를 건너뛰게 됩니다.

**시험 표본이 작습니다.** 시험은 4개 주제 그룹 20문항이며 검색 정답이 있는 것은 16개입니다. 주제별·질문 유형별 결과와 그룹 단위 변동을 함께 보고하세요. 시험셋을 검색/프롬프트 튜닝에 사용하면 새 시험셋이 필요합니다.

**반경 문항은 필터 기동 확인용입니다.** `TM-family_parks-04`는 반경 안에 후보가 1개뿐입니다. 회귀 테스트는 반경 안·밖·제외를 확인하지만, 실데이터 벤치마크의 경계/순위 다양성을 대신하지 않습니다.

**코퍼스 품질 문제를 숨기지 않았습니다.** 청담도로공원(394)은 임베딩이 없고 익선동 한옥거리(355)는 city가 없습니다. 현재 벡터 검색은 394를 반환하지 못할 수 있습니다. 골든셋에서 삭제하지 않고 색인/데이터 문제로 별도 집계합니다. 449건 모두 서울이며 다른 지역 성능을 대표하지 않습니다.

## RAGAS 연결

이 파일은 사용자 정의 검색 판정 형식입니다. RAGAS의 `user_input`에는 실제 질문·대화 입력을 넣고, `retrieved_contexts`와 `response`는 시스템을 실행한 결과로 채워야 합니다. 골든 evidence를 검색된 문맥처럼 복사하지 않습니다.

`required_facts`는 후보별 추천 판정 이유를 포함하며, 모범 답변 문자열 그 자체는 아닙니다. 정답이 필요한 지표에는 검수한 사실과 원문에서 reference를 작성하거나 해당 지표가 요구하는 형식으로 변환하세요. 일부 지표는 reference가 없어도 실행할 수 있습니다. 수정 완료나 자동 검사 통과를 RAGAS 성능 점수로 해석하지 않습니다.

## 버전별 폴더 관리

이 버전은 `Evaluation/v1.3.0/`에서 독립적으로 관리합니다. 다른 버전과 원본·산출물을 섞지 않습니다. [전체 버전 목록](../README.md)을 참고하세요.

## 작성 중인 리뷰 메모

- [질문별 리뷰 읽기](review_notes_by_question.md): 100문항·273행, 후보별 들여쓰기와 원문 인용
- [메모가 채워진 검수표](review_notes_filled_v1.3.0.csv): 기존 develop의 review.csv를 바이트 단위로 보존한 사본
- [평가 기준](evaluation_review_criteria.md): 검색 적합도와 생성 답변 평가를 구분한 기준
- [검토 메타데이터](review_notes_metadata.json)

`review.csv`는 이 버전의 작성 원본으로부터 재생성되는 검증 대상 파일입니다. 사용자가 검토할 메모는 `review_notes_filled_v1.3.0.csv`에서 이어서 작성하세요. `--build`는 메모 사본을 덮어쓰지 않습니다. 리뷰 반영은 `case_id + place_id`로 비교하고, 사람이 확정한 판정과 검수 이력을 작성 원본에 반영한 뒤 새 버전을 만드세요. AI 초안을 사람 검수 완료로 처리하지 않았습니다.
