# TravelMate 장소 검색 평가셋 v1.3.0

서울 관광지 449건과 TourAPI 원본 449건의 스냅샷을 기준으로 만든 질문 100개입니다. 현재 버전의 작성 원본·산출물·검수 자료를 함께 관리합니다.

**상태: 기존 100문항·273행의 사람 검수 완료 (`human_reviewed`).** 사용자가 대화에서 검수 완료를 확인해 검수자 표기 `user`와 확인 기록 시각을 작성 원본·CSV·JSONL에 반영했습니다. `user`는 실명 추정이 아닌 사용자 식별 표기이며, 기록 시각은 원래 검수 작업 시각이 아닙니다. 개발 검색 API와 공통 문항의 RAGAS ID 평가는 일부 실행됐으며, 전체 성능 측정은 아직 완료되지 않았습니다.

## 먼저 사용할 파일

- **LLM이 읽는 장소 평가 기준:** [LLM_JUDGE_RUBRIC.md](LLM_JUDGE_RUBRIC.md). [실행 방법](RAGAS_RUNNER.md#지금-필요한-평가-md-기준-llm-as-a-judge)의 `--mode judge`는 reference 없이 기존 0~3점 기준으로 판정합니다.
- **검수 완료 리뷰:** [review_notes_filled_v1.3.0.csv](review_notes_filled_v1.3.0.csv)
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

**기존 판정의 사람 검수는 완료됐습니다.** 사용자의 완료 확인을 작성 원본에 기록해 재생성해도 `human_reviewed`가 유지됩니다. 판정 점수·근거·메모는 변경하지 않았습니다. 사람 검수 완료가 미판정 후보까지 정답을 확정했다는 뜻은 아닙니다.

**부분 관련도 판정입니다.** 현재 질문–장소 판정은 253개, 판정한 장소는 72개입니다. 449건 전부에 대해 질문별 관련도를 판정한 것은 아닙니다. 남산골한옥마을을 보완했어도 다른 미판정 정답이 있을 수 있습니다. 키워드·dense·rerank의 상위 후보를 합쳐 추가 검수하고, `judged@K`와 미판정 처리 정책을 보고하세요. 미판정 후보를 자동 0점으로 두지 않습니다. Recall도 판정된 정답 집합을 기준으로 한 값임을 명시합니다.

**API와 평가 범위가 다릅니다.** `GET /api/places/search`의 질문·지역·도시·분류 입력으로는 `search_api.jsonl`을 평가합니다. 제외·대화·반경 입력을 처리하는 상위 흐름에는 `context_search.jsonl`을, 기권/추가 질문을 처리하는 대화 흐름에는 `answer_behavior.jsonl`을 연결합니다. 자연어 조건 추출까지 평가하려는 실험에서 정규화한 조건을 시스템에 미리 넣으면 그 단계를 건너뛰게 됩니다.

**시험 표본이 작습니다.** 시험은 4개 주제 그룹 20문항이며 검색 정답이 있는 것은 16개입니다. 주제별·질문 유형별 결과와 그룹 단위 변동을 함께 보고하세요. 시험셋을 검색/프롬프트 튜닝에 사용하면 새 시험셋이 필요합니다.

**반경 문항은 필터 기동 확인용입니다.** `TM-family_parks-04`는 반경 안에 후보가 1개뿐입니다. 회귀 테스트는 반경 안·밖·제외를 확인하지만, 실데이터 벤치마크의 경계/순위 다양성을 대신하지 않습니다.

**코퍼스 품질 문제를 숨기지 않았습니다.** 청담도로공원(394)은 임베딩이 없고 익선동 한옥거리(355)는 city가 없습니다. 현재 벡터 검색은 394를 반환하지 못할 수 있습니다. 골든셋에서 삭제하지 않고 색인/데이터 문제로 별도 집계합니다. 449건 모두 서울이며 다른 지역 성능을 대표하지 않습니다.

## RAGAS 연결

ID 지표 두 개와 OpenAI LLM 지표 세 개의 실행기는 [RAGAS_RUNNER.md](RAGAS_RUNNER.md)에 정리했습니다. `run_ragas_evaluation.py`는 실제 API 결과를 읽어 평가하며, `run.sh --check`는 계속 데이터셋 구조 검사만 수행합니다.

이 파일은 사용자 정의 검색 판정 형식입니다. RAGAS의 `user_input`에는 실제 질문·대화 입력을 넣고, `retrieved_contexts`와 `response`는 시스템을 실행한 결과로 채워야 합니다. 골든 evidence를 검색된 문맥처럼 복사하지 않습니다.

`required_facts`는 후보별 추천 판정 이유를 포함하며, 모범 답변 문자열 그 자체는 아닙니다. 정답이 필요한 지표에는 검수한 사실과 원문에서 reference를 작성하거나 해당 지표가 요구하는 형식으로 변환하세요. 일부 지표는 reference가 없어도 실행할 수 있습니다. 수정 완료나 자동 검사 통과를 RAGAS 성능 점수로 해석하지 않습니다.

### 기대 답변 작성과 JSONL 재생성

`reference`는 `cases.source.json`의 개별 문항에 작성합니다. 예를 들어 `TM-palaces-01`에 대응하는 `palaces` 그룹의 `case_suffix: 1` 문항에는 다음 필드를 추가할 수 있습니다.

```json
"reference": "요청하신 장소는 창경궁입니다."
```

위 문장은 장소 식별 질문에 대한 작성 예시이며 실제 데이터에 자동 입력하지 않습니다. 기존 문항의 다른 필드는 유지하고 기대 답변의 사실과 완결성을 사람이 검토하세요. 판정 해설이나 장소별 점수를 기대 답변으로 자동 변환하지 않습니다.

작성 원본을 수정한 뒤에는 반드시 다시 생성합니다. `--check`는 기존 JSONL을 검사하며 갱신하지 않습니다.

```bash
bash Evaluation/v1.3.0/run.sh --build
bash Evaluation/v1.3.0/run.sh --check
```

빌더는 원본의 `reference`를 `golden.jsonl`, `development.jsonl`, `test.jsonl`, `search_api.jsonl`, `context_search.jsonl`, `answer_behavior.jsonl`의 해당 문항에 그대로 전달합니다. 작성하지 않은 문항은 `"reference": null`로 표시합니다. 빈 문자열·공백뿐인 문자열·문자열이 아닌 값은 거부합니다.

검증 결과와 manifest에는 `reference_count`, `missing_reference_count`, `answerable_missing_reference_count`를 기록합니다. 구조 검증 통과가 기대 답변 작성 완료를 뜻하지 않습니다. 현재 원본에는 기대 답변이 없으므로 100문항 모두 미작성이고, 그중 답변 가능한 문항은 80개입니다.

Answer Correctness 등 정답이 필요한 평가에 앞서 답변 가능한 80문항의 기대 답변 누락을 차단하려면 다음 명령을 사용하세요.

```bash
bash Evaluation/v1.3.0/run.sh --check --require-reference
```

호스트 Python에서는 `python -X utf8 Evaluation/v1.3.0/build_dataset.py --check --require-reference`로 실행할 수 있습니다. 이 모드는 기대 답변이 빠진 답변 가능 문항이 있으면 실패하며 문항 ID를 표시합니다. 답변 불가·확인 질문 20문항은 별도 행동 기준으로 검수하므로 이 옵션에서 기대 답변을 강제하지 않습니다. 기대 답변이 모두 있어도 의미 검수나 실제 시스템 출력 수집이 완료됐다는 뜻은 아닙니다.

JSONL에 `reference`를 직접 추가하지 말고 작성 원본을 수정한 뒤 재생성하세요. 필드가 빠진 이전 JSONL이나 원본에서 수정한 기대 답변이 반영되지 않은 산출물은 검증기가 거부합니다. 재생성은 별도 리뷰 메모 파일을 덮어쓰지 않습니다.

## 버전별 폴더 관리

이 버전은 `Evaluation/v1.3.0/`에서 독립적으로 관리합니다. 다른 버전과 원본·산출물을 섞지 않습니다. [전체 버전 목록](../README.md)을 참고하세요.

## 작성 중인 리뷰 메모

- [질문별 리뷰 읽기](review_notes_by_question.md): 100문항·273행, 후보별 들여쓰기와 원문 인용
- [메모가 채워진 검수표](review_notes_filled_v1.3.0.csv): 기존 메모를 보존하고 사람 검수 완료 상태를 반영한 검수표
- [평가 기준](evaluation_review_criteria.md): 검색 적합도와 생성 답변 평가를 구분한 기준
- [검토 메타데이터](review_notes_metadata.json)

`review.csv`는 이 버전의 작성 원본으로부터 재생성되는 검증 대상 파일입니다. 메모는 `review_notes_filled_v1.3.0.csv`에 보관하며 `--build`는 이 파일을 덮어쓰지 않습니다. 이번 상태 정정은 사용자의 검수 완료 확인에 근거하며, AI의 자동 판정을 사람 검수로 표시한 것이 아닙니다. 이후 판정 변경은 `case_id + place_id`로 작성 원본에 반영하세요.

API 결과 파일에 부착된 장소 판정의 검수 상태도 동기화했습니다. 실제 검색 응답·순위·실행 시간·기존 평가 점수는 유지했습니다. 기존 `ragas_summary.json` 등의 `review_statuses`와 입력 해시는 평가 당시 기록이며 현재 검수 상태는 `manifest.json`, `validation.json`, `review_notes_metadata.json`에서 확인합니다.

## Development ranking comparison

The development run records two ranking versions for each answerable search case:

- `v1_semantic_only`: embedding similarity order before the BGE reranker.
- `v2_reranked`: BGE reranker order over the same top-30 embedding candidate pool.

Run `python -X utf8 Evaluation/v1.3.0/run_development.py --split development` to capture both versions. The comparison is scored against authored place judgments at `@5` and `@10`, including NDCG, MAP, MRR, Recall, Precision, and F1. Results are separated into `ranking_at_5/` and `ranking_at_10/`, each with `results.jsonl`, `summary.json`, and a live progress copy in `run.log`; the root ranking files remain the `@10` compatibility view. Each cutoff is also traced to its own LangSmith project. Judgments are partial, so unjudged places are not asserted to be irrelevant and the scores indicate the judged candidate pool only.
### Versioned RAGAS samples

`api_embedding/v1.jsonl` stores embedding-only API outputs; `api_reranking/v2.jsonl` stores reranked API outputs. Both contain place judgments from `review_notes_filled_v1.3.0.csv`, request duration, and metric-specific flags:

- `ranking_eligible`: the completed response has authored judgments for ranking evaluation.
- `ragas_id_metrics_eligible`: the completed response has at least one positive judged place ID for RAGAS ID-based Context Precision/Recall.
- `ragas_llm_eligible`: the completed response has complete condition coverage and an authored text `reference` for reference-based LLM metrics.

`run_ragas_evaluation.py` runs the RAGAS ID-based metrics against paired completed outputs using CSV judgments with relevance `>= 2` as reference IDs. It writes case scores to `ragas_results.jsonl` and averages and run scope to `ragas_summary.json`. These ID metrics compare sets and do not consider result order; use `ranking_results.jsonl` for order-sensitive NDCG/MRR. Each RAGAS result also records judged and unjudged retrieved ID counts. Because ID precision divides relevant retrieved IDs by all retrieved IDs, scores remain provisional while the review CSV is only partially judged. The current run contains one paired completed case; incomplete and failed API requests are excluded, not counted as search errors.

`ragas_llm_precheck.json` reports LLM metrics separately. Answer Correctness and basic LLM Context Recall require a reference. Faithfulness does not require a reference, but it does require an LLM evaluator and response/context inputs. The current policy runs these three metrics as one batch; the batch is deferred while the reference metrics lack references and no LLM evaluator is configured. The precheck records Faithfulness as deferred by that batch policy, not blocked by a missing reference.

`ragas_eligible` is no longer used because it did not identify which RAGAS metric family it referred to. Use `ragas_id_metrics_eligible` or `ragas_llm_eligible` instead.
Per-version API wall time is stored in each version file's `request_duration_seconds` and in `development.jsonl` at `ranking_comparison.<version>.execution.duration_seconds`. The paired total remains `execution.duration_seconds` on the development case.
