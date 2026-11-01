# 보존 응답 기반 문맥 검색 진단

기존 v1_local·v2 응답을 재생하고 후속 프롬프트를 비교한다. 보존 응답 재생은 문맥 생성 API를 호출하지 않는다.
실험 B의 `prompt_comparison.py generate`는 새 문맥을 실제 유료 생성한다. 계획 검증·내보내기·검색 실행은 이 호출과 분리한다.
문맥 생성 CLI의 `generate --execute`도 실제 유료 호출이며, `--execute` 없는 CLI 실행과 `span_inputs.py`는 준비만 한다.
`span_generation.py generate --execute`는 새 입력+v5 실제 유료 생성 검수이며 앞 실험 B와 별도 실행이다.
한 장소의 여러 입력 묶음은 각각 별도 색인으로 비교하며, 나중 묶음으로 앞 묶음을 덮어쓴 결과를 전체 데이터의 합집합으로 해석하지 않는다.

`pilot_cases.json`은 한 장소의 원문 22구간에서 만든 탐색적 질문 26개다.
독립 테스트셋이나 사람의 블라인드 평가가 아니며 v1.4.0 공용 평가셋과 분리한다.
`pilot_review.json`은 원문 구간별 에이전트 검수 기록이다. 검수 플래그는 중복 가능하다.
[2026-10-31 실측 보고서](../../runs/contextual/stored-nine-pairs/20261031-01/REPORT.md)에 결과와 한계를 기록했다.
[문제 정의와 해결 실험안](PROBLEMS_AND_SOLUTIONS.md)은 문맥 생성·혼합 장소 분할·리랭킹 근거 전달의 문제를 구분하고 후속 비교 기준을 제안한다. 서비스 적용 전 설계 문서다.
[근거 1·2·3개 비교 실측](../../runs/contextual/multi-evidence-v1/20261031-01/REPORT.md)에서 실험 A의 구현·검증 결과를 확인한다.
[v2·v4 프롬프트 비교 실측](../../runs/contextual/prompt-grounding-v1/20261031-01/REPORT.md)에서 근거 2개를 고정한 실험 B의 결과를 확인한다.
[명시적 청크 입력 준비](../../runs/contextual/span-inputs-v1/20261101-01/REPORT.md)는 실측 품질 비교와 구분한 후속 구현 기록이다.

## 명시적 원문 입력과 분할 후보 준비

다음 명령은 저장 v4 응답을 읽고 요청·분할 후보·해시만 만든다. 키·HTTP 클라이언트·DB를 초기화하지 않는다.

```powershell
python -X utf8 -m Evaluation.tracks.contextual.span_inputs --generation-summary <보존-v4-generation-summary.json> --output <새-준비-폴더>
python -X utf8 -m Evaluation.tracks.contextual.span_inputs --audit-batch <새-준비-폴더>/batch-plan.json
```

단일 기록은 `--generation-summary` 대신 `--record <v4-record.json>`을 쓴다.
각 묶음의 `request.explicit.json`은 지시문을 유지하고 각 입력 span에 정확한 `chunk_text`만 추가한다.
`split-candidates.json`의 구조 기반 후보는 이 요청에 적용되지 않는다. 새 문맥·장소 역할·검색 청크로 간주하지 않는다.
요청/후보/계획 해시와 원본 4개 파일을 감사하고, 기존 실행 폴더·동결 데이터셋을 덮어쓰지 않는다.
전체 원문·요청은 로컬 보존 자료로 관리하고, 원격에는 집계·해시·구현 기록만 게시한다.

아래는 `embedding-server`에서 실행하는 **미리보기** 예다. `--execute`가 없으므로 유료 호출하지 않는다.

```powershell
python -m app.contextual.cli generate --baseline-record <보존-v4-record.json> --prompt-version contextual-source-spans-v4 --input-version source-explicit-chunks-v2 --output <새-미리보기-폴더> --comparison-output <짧은-보고서-폴더>
```

입력 비교에서는 같은 프롬프트를 명시해야 한다. 입력·지시문을 동시에 바꾸면 거부한다.
현재 규칙으로 재검증하지 않은 예전 대조군은 먼저 무료 `revalidate`로 새 기록을 만든다.
기존 ‘프롬프트만 비교’ 검증을 완화해 새 입력을 통과시키지 않는다.
추후 v4 명시적 입력의 실제 응답이 생기면 그것을 대조군으로, `--prompt-version contextual-source-spans-v5`를 선택한다.
이때 `--input-version`을 생략하면 대조군의 명시적 입력을 유지하며 지시문만 비교한다.
v5는 명시적 청크를 직접 읽고 위치 계산을 하지 않도록 지시한다. 아래 실제 문맥 검수에서 일부 오류 감소와 귀속 회귀를 확인했고 검색은 평가하지 않았다.

구조 기반 후보는 부모 청크 안에서만 원문을 잘게 나눈다. 장소 경계 정답이나 운영 분할 전략으로 확정한 결과가 아니다.
분할 전략 채택과 장소별 20개 상한·전체 출처 동시 색인은 별도 C·D 실험에 남긴다.

## 새 입력 + v5 실제 문맥 검수

[실행·검수 결과](../../runs/contextual/span-grounding-v1/20261101-01/REPORT.md): 새 응답 9개·US$0.01681,
다른 청크의 주제 대체 2→0과 혼합 장소 귀속 회귀 1건을 함께 기록했다. v5를 기본값으로 바꾸지 않았다.
입력·지시문을 함께 바꾼 `explicit-input-and-instructions` 검수이며 입력 형식만의 효과로 해석하지 않는다.

```powershell
python -X utf8 -m Evaluation.tracks.contextual.span_generation prepare --batch <보존-batch-plan.json> --prepared <기존-prepared.json> --output <새-실행-폴더>
python -X utf8 -m Evaluation.tracks.contextual.span_generation generate --plan <새-실행-폴더>/plan.json --key-file <지정-키-파일> --execute
python -X utf8 -m Evaluation.tracks.contextual.span_generation audit --plan <새-실행-폴더>/plan.json
python -X utf8 -m Evaluation.tracks.contextual.span_generation export-review --plan <새-실행-폴더>/plan.json
python -X utf8 -m Evaluation.tracks.contextual.span_generation summarize-review --plan <새-실행-폴더>/plan.json --review Evaluation/tracks/contextual/prompt_v5_review.json --output <새-실행-폴더>/quality-summary.json
```

위 `generate --execute`는 **유료 호출**이다. 완료된 이번 실행을 다시 생성할 필요는 없다.
기존 전송 시도나 생성 요약이 있으면 재시도를 거부한다. 실패 또는 실제 모델 불일치에서 뒤 호출을 중단한다.
나머지 명령은 키나 모델을 사용하지 않는다. `summarize-review`는 사람이든 에이전트든 이미 기록한 판정을 집계할 뿐 새 의미 판정을 하지 않는다.
전체 생성 응답의 스키마·오프셋 통과와 원문 대비 문맥 정확성을 구분한다. 새 분할·재색인·검색 측정은 실행하지 않았다.

## 관찰 분할·이동 관계 선택 계약

관찰 경계·이동 관계의 후속 선택 계약은 [v6 구현·검수 기록](../../runs/contextual/observation-spans-v1/20261101-01/REPORT.md)에 있다.
장소 이름 수로 나누지 않고 이동 문장은 하나로 유지한다. 자동 판정과 검수 후 선택을 구분한다.
워커의 내용 종류·이동 방향 필터는 명시적 입력만 받으며 자연어 자동 선택은 구현하지 않았다.

```powershell
python -X utf8 -m Evaluation.tracks.contextual.observation_generation prepare --summary <보존-v5-generation-summary.json> --regressions Evaluation/tracks/contextual/observation_regressions.json --pairs P08 P09 --output <새-실행-폴더>
python -X utf8 -m Evaluation.tracks.contextual.observation_generation generate --plan <새-실행-폴더>/plan.json --key-file <지정-키-파일> --execute
```

`generate --execute`는 **유료 호출**이다. 이번 보존 응답을 다시 생성할 필요는 없다.
기존 전송 시도·요약이 있으면 자동 재시도하지 않는다. 받은 응답의 처리 오류는 원본을 유지하고 무료 `revalidate`부터 검토한다.
분할·지시문·출력 스키마·검증 버전이 함께 바뀐 계약 검수이며 지시문만의 비교와 섞지 않는다.

`embedding-server`의 명시적 준비·검수 명령은 다음과 같다. 아래에는 `--execute`나 DB 적용이 없다.

```powershell
python -m app.contextual.cli generate --input <sources.json> --prompt-version contextual-observation-relations-v6 --input-version source-explicit-chunks-v2 --splitter-version sentence-paragraph-v2 --model perplexity/sonar --output <미리보기-폴더>
python -m app.contextual.cli review --record <검수한-record.json> --reviewer <검수자> --approve <승인-청크-UUID> --output <승인파일.json>
python -m app.contextual.cli selection --record <검수한-record.json> --review <승인파일.json> --output <선택보고서.json>
```

`--approve`를 여러 번 주거나 생략해 모두 보류할 수 있다. 새 계약의 `apply`에는 `--review`가 필요하다.
승인 파일은 실제 원본 해시에 묶이며 검증 오류·귀속 보류 구간의 ID는 승인할 수 없다.
`review/selection`은 원본·요청·응답을 수정하지 않는다. 실제 DB 적용은 별도 명령이며 이번에는 실행하지 않았다.

## 프롬프트 비교 실험 B

```powershell
python -X utf8 Evaluation/tracks/contextual/prompt_comparison.py prepare --prepared <기존-prepared.json> --cases <고정-질문> --output <새-실험-폴더>
python -X utf8 Evaluation/tracks/contextual/prompt_comparison.py generate --plan <새-실험-폴더>/plan.json --key-file <명시적-키-파일>
python -X utf8 Evaluation/tracks/contextual/prompt_comparison.py export --plan <새-실험-폴더>/plan.json
```

`prepare`는 9개 v2 요청의 지시문만 v4로 바꾼 계획·해시를 기록하며 키나 HTTP 클라이언트를 초기화하지 않는다.
`generate`는 실제 모델 호출 명령이다. 키 파일 하나를 직접 읽고 키·인증 헤더는 저장하지 않는다.
기존 성공 캐시를 재사용하고 실패·실제 모델 불일치가 있으면 뒤의 호출을 중단한다. 완료/중단 요약이 있으면 자동 재시도하지 않는다.
전송 시도와 실제 응답 usage를 분리한다. 비교 보고서는 짧은 별도 폴더에 보존해 Windows 경로 한계를 피한다.

아래 검색 명령은 기존 컨테이너 임시 경로에서 실행한다. 입력 이름 `v2`·`v4`와 근거 수 `2`를 명시한다.

```text
python retrieve.py --code <최신-app의-상위경로> --inputs retrieval-inputs.json --cases cases.frozen.json --output <새-검색-폴더> --baseline-name v2 --candidate-name v4 --evidence-count 2
```

원문 구간과 양쪽 실제 응답을 연결한 로컬 `prepared-comparison.json` 및 검수 기록을 사용해 집계한다.
기존 `retrieve.py`·`score.py` 명령의 기본 비교 이름은 v1·v2, 검색 기본 근거 수는 1개로 유지된다.

```powershell
python -X utf8 Evaluation/tracks/contextual/score.py --prepared <prepared-comparison.json> --cases <고정-질문> --results <새-검색-폴더> --review Evaluation/tracks/contextual/prompt_v4_review.json --output <새-실험-폴더>/scores.json --baseline-name v2 --candidate-name v4
python -X utf8 Evaluation/tracks/contextual/audit_prompt.py --results <새-실험-폴더> --prior-observations Evaluation/runs/contextual/multi-evidence-v1/20261031-01/observations.json --output <새-실험-폴더>/audit.json
```

전체 원문·응답·준비 자료·벡터는 로컬 아카이브에 보존한다. 게시본의 집계와 원문 검수·실제 검색 재실행에 필요한 자료 범위를 구분한다.

## 근거 수 비교 실험 A

`multi_evidence.py`는 아래 입력으로 보존 v2만 활성화하고 근거 1·2·3개를 질문마다 3회 반복한다.
실제 `_complete_recommendation`을 실행하며 후보 30개·대표 근거가 모든 비교에서 같지 않으면 중단한다.
기존 `retrieve.py`와 `score.py`를 같은 컨테이너 임시 경로에 두고 기존과 같은 방식으로 실행한다.

```text
python multi_evidence.py --code <최신-app의-상위경로> --inputs retrieval-inputs.json --cases cases.frozen.json --prepared prepared.json --vectors vectors.json --output <새-실험-폴더> --repetitions 3
python stress_evidence.py --code <최신-app의-상위경로> --source <새-실험-폴더> --vectors vectors.json --output <새-부하-폴더>
```

입력·준비 자료·벡터는 앞 비교의 로컬 보존 자료를 재사용한다. 실행 조건은 batch 8·autocast_fp16이며 별도 모델을 로드하지 않는다.
품질·지연 기록은 `observations.json`·`summary.json`, 실제 쌍별 입력·점수·전체 응답은 질문별 JSON에 쓴다.
쿼리 벡터는 재사용하므로 기록한 코어 지연은 실제 임베딩 호출이나 Spring/Kafka 전체 지연을 포함하지 않는다.
GPU 계측은 nvidia-smi의 장치 전체 메모리 100ms 표본이다. PyTorch의 정확한 최대 할당량이나 서버 내부 대기 시간으로 표시하지 않는다.
별도의 부하 실험은 실제 후보 텍스트를 반복한 30·60·90쌍이며 장소 검색 품질 점수가 아니다.

```powershell
python -X utf8 Evaluation/tracks/contextual/audit_multi.py --results <새-실험-폴더> --cases <고정-질문> --baseline Evaluation/runs/contextual/stored-nine-pairs/20261031-01/scores.json --output <새-실험-폴더>/audit.json
python -X utf8 -m unittest Evaluation.tracks.contextual.test_score Evaluation.tracks.contextual.test_multi
```

감사는 반복·비교 상대 누락, 입력 후보 변경, subject가 아닌 근거 전달, 단일 근거 기준군의 기존 v2 결과 회귀를 검사한다.
모델이 잘못 subject로 붙인 의미 오류는 형식 감사로 해결되지 않으며 문맥 검수와 함께 해석한다.

## 입력 준비

저장소 루트에서 임베딩 서버 의존성이 설치된 Python으로 실행한다.
`prepare`는 비교 완료된 재검증 보고서를 읽고 원본 해시·동일 요청 조건·실제 모델·검증 버전을 확인한다.
`export`는 검증된 검색 청크를 컨테이너에서도 읽을 수 있는 JSON으로 내보낸다.

```powershell
python -X utf8 Evaluation/tracks/contextual/compare.py prepare --batch-report <재검증-report.json> --output <새-평가-폴더>
python -X utf8 Evaluation/tracks/contextual/compare.py inspect --prepared <평가-폴더>/prepared.json --sources-only
python -X utf8 Evaluation/tracks/contextual/compare.py export --prepared <평가-폴더>/prepared.json --output <평가-폴더>/retrieval-inputs.json
```

원문을 읽어 질문과 기대 구간을 고정한 뒤 응답을 검수한다. 기존에 응답을 보았다면 블라인드라고 표시하지 않는다.
질문 파일은 실행 전에 별도 복사하고 해시를 보존한다. Q10 문장은 불필요한 인과로 읽힐 수 있어 현재 진단에서는 제외한 민감도 집계도 함께 기록한다.

## 격리 검색 실행

실행 중인 임베딩 컨테이너에 최신 `embedding-server/app/`을 서비스 경로와 다른 임시 경로로 복사한다.
`retrieve.py`와 입력·고정 질문도 임시 경로에 둔다. 실행 프로세스에는 asyncpg·httpx·jsonschema·기존 서버 의존성이 필요하다.
누락 의존성은 전용 임시 `--target` 경로로 설치하고 `PYTHONPATH`로 지정할 수 있다. 서버 패키지·서비스 코드는 바꾸지 않는다.

```text
python retrieve.py --code <최신-app의-상위경로> --inputs inputs.json --cases cases.frozen.json --output <새-결과-폴더>
```

컨테이너의 `DATABASE_URL`로 연결하되 출력하지 않는다. 아래 작업만 수행한다.

1. 공개 장소 테이블을 같은 트랜잭션 스냅샷에서 두 개의 무작위 임시 스키마에 복제한다.
2. 임시 테이블에만 최신 enrichment/contextual 스키마를 적용한다.
3. 각 입력 쌍의 subject 청크와 TourAPI 보조 청크를 실제 `select_active`·`activate_chunks`로 색인한다. 기존 enrichment 스냅샷은 추가하지 않는다.
4. 현재 서버의 `/embed`·`/rerank`로 실제 모델을 재사용한다. 같은 GPU에 모델을 다시 올리지 않는다.
5. 최신 `KafkaRuntime._complete_recommendation`을 실행한다. 결과 저장만 파일로 대체하며 장소별 근거 1개·후보 30개·리랭킹·최종 20개는 실제 코드를 사용한다.
6. 생성한 임시 스키마를 정리하고 공개 장소 전체 행의 전후 해시를 기록한다.

동일 질문 벡터는 두 버전에 재사용한다. 실행 순서는 질문마다 교대한다.
실패한 실행 폴더를 지우거나 덮어쓰지 않고 다른 실행 폴더로 재시도한다.
이 실행은 실제 검색 코어 비교이며 Spring/Kafka 전달, 큐 지연, 최종 답변 생성이나 서비스 전체 성능 측정이 아니다.

## 집계

```powershell
python -X utf8 Evaluation/tracks/contextual/score.py --prepared <평가-폴더>/prepared.json --cases <평가-폴더>/cases.frozen.json --results <평가-폴더>/retrieval --review Evaluation/tracks/contextual/pilot_review.json --output <평가-폴더>/scores.json
python -X utf8 -m unittest Evaluation.tracks.contextual.test_score
```

목표 장소가 상위에 있는지와 선택 근거의 source/version/offset이 기대 구간과 일치하는지를 따로 집계한다.
모든 장소의 관련성을 판정한 것이 아니므로 이 목표 적중률을 전체 검색 정확도·재현율로 표현하지 않는다.
근거 없는 질문은 잘못된 출처 노출과 장소 반환을 관찰한다. 최종 답변을 생성하지 않았으므로 답변 환각률로 표현하지 않는다.
실행 결과는 질문별 원본 파일, 벡터, 활성 청크, 코드·입력 해시, 완료 목록과 정리 확인서로 보존한다.


## 핵심·보조 관계의 독립 보존

v7은 경관·시설 원문에도 `importance=primary/supporting` 이동 관계를 보존한다.
[코드 회귀·호환 검증](../../runs/contextual/supporting-relations-v1/20261101-01/REPORT.md)은 합성 응답과 보존 기록 읽기로만 확인했다.
기존 v6 응답을 중요도가 있는 것처럼 바꾸거나 다시 생성하지 않는다.

```powershell
python -X utf8 -m Evaluation.tracks.contextual.supporting_relations --output <새-결과.json>
```

이 명령은 합성 A/B 관계의 역할·방향·비중·리랭킹 사용 범위만 검사한다. 키·HTTP 클라이언트·DB·검색 모델을 사용하지 않는다.
실제 Sonar 생성 품질이나 검색 성능을 측정하는 명령이 아니다.


## 실제 v7 통합 검증

[실행 기록](../../runs/contextual/v7-integration-v1/20261101-01/REPORT.md)은 격리 PostgreSQL과 기존 CUDA 모델을 사용한다.
`Dockerfile.integration`은 기존 로컬 이미지에 httpx/jsonschema만 추가한다. 앱 코드는 읽기 전용 마운트로 제공한다.
`isolated_database`는 tm-v7-eval- 호스트/contextual_v7_eval DB 이름을 요구하며 운영 DB를 허용하지 않는다.
`--full`은 기존 DB 회귀도 포함한다. 모델 검색은 별도 `v7_search`/`v7_recall_audit` 명령이다.

```powershell
python -m Evaluation.tracks.contextual.v7_generation prepare --baseline-record <보존-P09-record.json> --output <새-폴더>
# 유료: 최대 2회. 기존 호출 기록이 있으면 중단한다.
python -m Evaluation.tracks.contextual.v7_generation generate --plan <새-폴더>/plan.json --key-file <키파일> --execute
```

보존된 두 응답을 다시 호출할 필요는 없다. 검색 스크립트는 해당 동결 실행 자료를 검수한 뒤 별도 폐기용 DB에서 실행한다.
위치 정렬·후보 확대·슬롯 교체는 감독 진단으로 구분하며 원래 v7 응답이나 검증 규칙을 수정하지 않는다.
