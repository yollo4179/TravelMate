# Ragas 실행기: ID 평가와 OpenAI LLM 평가

## 지금 필요한 평가: MD 기준 LLM-as-a-Judge

**기존 사람/AI 검수표의 장소별 0~3점과 근거는 이미 유효한 평가 자료입니다. 문장형 모범 답변을 새로 쓰지 않아도 됩니다.** 장소 추천의 적합도를 LLM이 판정하게 하려면 다음 명령을 사용합니다. 저장소 루트 기준입니다.

```powershell
python Evaluation/v1.3.0/run_ragas_evaluation.py --mode judge --env-file .env
```

이 모드는 [LLM_JUDGE_RUBRIC.md](LLM_JUDGE_RUBRIC.md)를 실제 프롬프트에 읽어 넣고 다음 자료를 사용합니다.

1. `golden.jsonl`: 질문·대화·필터·필수 조건. `reference`·정답 ID 목록·장소별 정답 점수는 모델에 보내지 않습니다.
2. API JSONL: 실제 반환된 장소와 순서. 기존처럼 양쪽 버전의 공통 완료 문항을 사용합니다.
3. `corpus.json`: 이름·설명·지역 등 장소 원문과 필요한 상위/하위 시설 관계 근거.
4. `review_notes_filled_v1.3.0.csv`: 모델이 먼저 채점한 뒤 기존 판정과 대조합니다. 정답 점수를 그대로 따라 쓰게 하지 않습니다.

`reference: null`이어도 실행하며 평가 임베딩도 필요하지 않습니다. 이미 선택한 `gpt-4.1-mini`와 본인 OpenAI 키를 사용합니다. `--rubric 파일경로`로 수정한 MD를 명시할 수도 있고, 사용한 MD의 SHA-256을 결과에 기록합니다.

결과는 `llm_judge_results.jsonl`, `llm_judge_summary.json`에 저장하며 `llm_judge_precheck.json`은 키·원문·평가 입력 상태를 기록합니다. 각 장소의 0~3점·이유·원문 인용과, 판정돼 있던 장소의 CSV 점수를 함께 확인할 수 있습니다. 미판정 장소의 새 점수는 AI 판정으로 구분하고 기존 검수표·골든셋은 덮어쓰지 않습니다.

이는 MD 기준의 사용자 정의 장소 관련도 평가입니다. 아래의 Ragas 내장 Answer Correctness·Faithfulness·Context Recall 세 지표와 같은 점수라고 표시하지 않습니다. 기존 `--mode id`, `--mode llm`, `--mode all`의 의미와 기본값은 유지합니다. **현재 장소 Judge 목적에는 위 `--mode judge` 명령을 사용하세요.**

---

아래는 기존 **ID 지표 두 개**와 **Ragas 내장 LLM 지표 세 개**에 대한 설명입니다. 내장 LLM 세 지표는 두 버전의 공통 완료 문항을 대상으로 함께 실행하며, 요건이 하나라도 부족하면 세 지표 전체를 보류합니다. 위의 MD Judge는 별도 모드이므로 이 reference 조건에 묶이지 않습니다. 이 실행기는 검색 API를 다시 호출하거나 골든셋·리뷰·API 결과를 수정하지 않습니다.

## 1. 모델과 API 키

사용자가 선택한 설정을 [ragas_config.json](ragas_config.json)에 저장했습니다.

- 평가 LLM: `gpt-4.1-mini`
- 평가용 임베딩: `text-embedding-3-small`
- Answer Correctness 기본 가중치: 사실 일치 0.75, 의미 유사도 0.25
- API 키: 본인 OpenAI 프로젝트의 `OPENAI_API_KEY` 하나. 모델별로 다른 키를 발급하지 않습니다.

이 조합은 초기 비용·연결 편의성을 고려해 제안한 뒤 사용자가 선택한 것입니다. 실제 TravelMate 평가에서 가장 우수하다고 측정한 조합이라는 뜻은 아닙니다. 장소 검색용 BGE-M3와 생성용 Qwen은 변경하지 않습니다. 필요하면 `RAGAS_JUDGE_MODEL`, `RAGAS_EMBEDDING_MODEL` 환경변수로 모델을 명시할 수 있으며 결과에 실제 모델명을 기록합니다.

키를 JSON 설정·소스·Git에 넣지 않습니다. 환경변수를 사용하거나, 로컬 `.env`에 다음 항목을 작성하고 `--env-file`로 경로를 지정하세요.

```dotenv
OPENAI_API_KEY=본인_OpenAI_API_키
```

다른 사용자의 공용 키를 제공하는 기능은 없습니다. API 프로젝트의 모델 권한·사용 한도가 필요하며 ChatGPT·Codex 구독과 API 이용 설정은 별개입니다. 키가 존재한다는 사전 검사와 실제 API 인증 성공을 구분합니다.

## 2. 평가 환경 설치

PowerShell에서 저장소 루트 기준입니다. 기존 서버 환경과 분리한 가상환경을 권장하며 활성화 스크립트 없이 실행할 수 있습니다.

```powershell
python -m venv .venv-ragas
.\.venv-ragas\Scripts\python.exe -m pip install -r Evaluation/v1.3.0/requirements-evaluation.txt
```

Ragas 0.4.3과 호환되는 `langchain-community==0.3.31`을 명시했습니다. community 0.4.x에서 제거된 모듈을 Ragas 0.4.3이 가져오는 문제를 피하기 위한 고정입니다. 기존 루트 requirements 전체를 바꾸지 않습니다.

이미 로컬에서 같은 이름의 실행기를 작성했다면 Git 갱신 전에 사본을 보관하세요. 이번 실행기는 `ragas_support/` 모듈도 함께 사용하므로 Python 파일 하나만 교체하지 말고 해당 커밋 전체를 받습니다. 기존 API JSONL·점수 파일·로컬 `.env`는 구현 파일에 포함하거나 덮어쓰지 않습니다.

## 3. 실제 입력 파일

아래 기존 로컬 파일을 그대로 사용합니다. 이번 구현에서 테스트 결과나 문장형 정답을 만들어 입력하지 않습니다.

```text
Evaluation/v1.3.0/
├── api_embedding/v1.jsonl
├── api_reranking/v2.jsonl
├── review_notes_filled_v1.3.0.csv
├── golden.jsonl
├── ragas_config.json
└── run_ragas_evaluation.py
```

- CSV의 `relevance >= 2` 장소 ID가 ID 평가의 정답입니다. 미판정 장소를 별도 표시하며, ID Precision 계산에서는 양성 정답 집합에 없는 반환 ID도 분모에 포함됨을 명시합니다.
- 이전 실행기와 같은 완료 상태·조건 완전성을 확인해 두 버전의 공통 문항을 고릅니다. 실패·미실행·조건 일부 적용 문항은 별도 제외 수로 기록합니다.
- API 파일의 예전 `ragas_eligible`, `ragas_id_metrics_eligible`, `ragas_llm_eligible` 값에 의존하지 않고 현재 입력과 설정으로 조건을 재검사합니다.
- `user_input`, `response`, `retrieved_contexts`는 실제 API 실행값을 사용합니다. CSV 해설을 답변으로 바꾸거나 골든 근거를 검색 결과로 복사하지 않습니다.
- `reference`는 `golden.jsonl` 또는 API 입력에 작성한 기대 답변 문자열을 연결합니다. 자연어 문장뿐 아니라 사용자가 정한 구조화 정답의 JSON 문자열도 입력할 수 있으며, 실행기가 정답 형식을 대신 정하거나 변환하지 않습니다. 골든에 작성한 reference를 사용하면 API를 다시 실행하지 않아도 됩니다. 둘 다 값이 있으면서 서로 다르면 조용히 하나를 선택하지 않고 동기화를 요청합니다.
- 현재 API의 `response`가 장소 목록 JSON 문자열이라면 그 실제 내용을 평가합니다. 이 결과를 자연어 가이드 발화 품질이나 계획 저장 성공률로 해석하지 않습니다.

작성 원본의 reference를 수정했다면 기존 절차대로 `--build`로 golden과 분할 파일을 먼저 재생성하세요. 기대 답변을 자동 생성하거나 사람 검수 완료로 바꾸지 않습니다.

## 4. 지표별 검사

모든 LLM 지표에 질문이 필요합니다. 나머지 요건은 다음과 같습니다.

| 지표 | 실제 응답 | 검색 문맥 | reference | LLM 평가기 | 평가용 임베딩 |
|---|---|---|---|---|---|
| ID Precision / ID Recall | 불필요 | ID 사용 | 장소 ID 정답 사용 | 불필요 | 불필요 |
| Answer Correctness | 필요 | 불필요 | 필요 | 필요 | 필요 |
| Faithfulness | 필요 | 필요 | 불필요 | 필요 | 불필요 |
| LLM Context Recall | 불필요 | 필요 | 필요 | 필요 | 불필요 |

검사는 **선택된 공통 완료 문항**에 적용합니다. 전체 입력의 reference 누락은 `source_missing_reference_case_ids`, 실제 LLM 배치를 막는 누락은 각 지표의 `missing_reference_case_ids`로 구분합니다. 입력에 미실행 60문항이 있다는 이유만으로 이미 완료된 공통 문항의 평가를 막지는 않습니다.

다음 사전 검사는 OpenAI를 호출하지 않으며, 키가 유효한지까지 보장하지 않습니다.

지표별 `status: ready`는 해당 지표의 입력 준비 상태입니다. 다른 지표 때문에 배치가 보류되면 `deferred_by_batch_policy: true`이고, 전체 상태는 미실행으로 유지됩니다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/v1.3.0/run_ragas_evaluation.py --env-file .env --precheck-only
```

## 5. 실행

기본값은 ID 두 지표를 실행하고, 요건이 충족되면 LLM 세 지표를 함께 실행하는 `all`입니다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/v1.3.0/run_ragas_evaluation.py --env-file .env
```

명시적으로 한 종류만 실행할 수도 있습니다. LLM 모드에서도 세 지표를 임의로 따로 실행하지 않습니다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/v1.3.0/run_ragas_evaluation.py --mode id
.\.venv-ragas\Scripts\python.exe Evaluation/v1.3.0/run_ragas_evaluation.py --env-file .env --mode llm
```

다른 입력·출력 위치는 `--root`, `--output-dir`로 지정합니다. `--config`로 별도 모델 설정 파일도 지정할 수 있습니다. `.env`는 명시한 파일만 읽고 이미 설정된 환경변수를 덮어쓰지 않습니다.

종료 코드는 0=요청한 평가 완료, 1=입력/실행 오류, 2=사전 요건 미충족입니다. `all`에서 ID는 완료됐지만 LLM이 보류된 경우 2입니다. 보류를 LLM 평가 성공으로 출력하지 않습니다.

## 6. 결과 파일

| 파일 | 내용 |
|---|---|
| `ragas_results.jsonl` | 기존 ID 두 지표의 버전별·문항별 결과 |
| `ragas_summary.json` | ID 평균·공통 문항 수·미판정 주의·입력 해시 |
| `ragas_llm_precheck.json` | 지표별 준비 상태·누락 사유·전체 보류 정책·설정/연결 구분 |
| `ragas_llm_results.jsonl` | LLM 세 지표가 모두 끝난 경우에만 쓰는 문항별 결과 |
| `ragas_llm_summary.json` | LLM 평균·모델·가중치·상태·입력 해시·평가 소요시간 |

전체 LLM 계산을 마치기 전에는 결과 파일을 교체하지 않습니다. 중간 실패·보류 시 예전 LLM 결과 파일이 존재하면 보존하되, 현재 summary는 `score_count: 0`, `results_file: null`로 기록합니다. 예전 파일을 이번 성공 결과로 읽지 마세요. 결과와 summary의 `run_id`가 일치하는지도 확인할 수 있습니다.

실제 OpenAI 인증·권한·한도·접속 오류는 실패 상태와 오류 유형으로 기록하며 키나 제공자 오류 원문은 결과에 저장하지 않습니다. 실제 LLM 평가를 모두 완료한 뒤에만 연결 확인 상태를 표시합니다. 평가기 자체의 소요시간은 기존 검색 API 지연시간과 분리합니다.

## 7. LangSmith Observability (랭스미스 관측)

평가기의 OpenAI 호출과 문항별 RAGAS 지표 점수를 LangSmith에 기록합니다. 루트 `.env`의 `OPENAI_API_KEY`와 LangSmith 추적 설정을 사용하며, 실행할 때 `--env-file .env`를 전달합니다. API 키가 저장소에 커밋되지 않도록 주의하세요.

기본 평가 환경과 분리된 관측 패키지를 설치합니다.

```powershell
.\.venv-ragas\Scripts\python.exe -m pip install -r Evaluation/v1.3.0/requirements-langsmith-observability.txt
```

순위 평가를 실행하면 v1 임베딩 검색과 v2 리랭킹 각각의 Precision@10, Recall@10, F1@10, NDCG@10, MAP@10, MRR@10이 문항별 trace로 기록됩니다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/v1.3.0/evaluate_ranking.py --env-file .env
```

추적을 켜고 평가를 실행합니다. `--mode judge`는 실제 검색된 장소를 Markdown 기준으로 보조 채점합니다. 이 결과는 사람 검수 CSV를 대체하지 않습니다. OpenAI API 호출 비용이 발생할 수 있습니다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/v1.3.0/run_ragas_evaluation.py --env-file .env --mode judge
```

LangSmith에서 `travelmate-ragas-v1.3.0` 프로젝트를 열면 모델 입력·출력과 문항별 지표 점수를 확인할 수 있습니다. trace에는 질문, 검색 문맥, 모델 답변이 포함될 수 있습니다. 해당 데이터를 LangSmith로 전송할 수 있는 환경에서 실행하세요. 기본 LLM 평가(`--mode llm`)는 대상 문항에 `reference`, `response`, `retrieved_contexts`가 모두 준비된 경우에만 실행됩니다.

## 8. 검증

```powershell
.\.venv-ragas\Scripts\python.exe -m unittest discover -s Evaluation/v1.3.0/tests -v
```

데이터셋 회귀 검사와 실행기 검사를 함께 수행합니다. 실행기 통합 검사는 실제 Ragas 지표와 OpenAI SDK에 모의 HTTP 응답을 연결하므로 유료 API를 호출하지 않습니다. 이는 라이브 OpenAI 키의 인증·할당량 검증이나 TravelMate의 실제 LLM 평가 점수 산출을 뜻하지 않습니다. Ragas가 없는 기본 Python 환경에서는 두 통합 검사만 건너뛰고 나머지 실행기 검사는 수행할 수 있습니다.
