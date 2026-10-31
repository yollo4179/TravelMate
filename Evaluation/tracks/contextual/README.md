# 보존 응답 기반 문맥 검색 진단

기존 v1_local 실행과 v2 응답을 재생한다. 문맥 생성 API는 호출하지 않는다.
한 장소의 여러 입력 묶음은 각각 별도 색인으로 비교하며, 나중 묶음으로 앞 묶음을 덮어쓴 결과를 전체 데이터의 합집합으로 해석하지 않는다.

`pilot_cases.json`은 한 장소의 원문 22구간에서 만든 탐색적 질문 26개다.
독립 테스트셋이나 사람의 블라인드 평가가 아니며 v1.4.0 공용 평가셋과 분리한다.
`pilot_review.json`은 원문 구간별 에이전트 검수 기록이다. 검수 플래그는 중복 가능하다.
[2026-10-31 실측 보고서](../../runs/contextual/stored-nine-pairs/20261031-01/REPORT.md)에 결과와 한계를 기록했다.
[문제 정의와 해결 실험안](PROBLEMS_AND_SOLUTIONS.md)은 문맥 생성·혼합 장소 분할·리랭킹 근거 전달의 문제를 구분하고 후속 비교 기준을 제안한다. 서비스 적용 전 설계 문서다.
[근거 1·2·3개 비교 실측](../../runs/contextual/multi-evidence-v1/20261031-01/REPORT.md)에서 실험 A의 구현·검증 결과를 확인한다.

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
