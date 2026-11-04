# 새 질문 검색 평가셋 v1.0.0

폴더 이름 `search-holdout-v1.0.0`은 **검색 독립 평가셋 첫 버전**이라는 뜻이다.
`search`는 검색, `holdout`은 모델·설정 조정에 쓰지 않고 최종 확인용으로 따로 남겨 둔 문항,
`v1.0.0`은 이 평가셋의 첫 버전을 가리킨다. 앱이나 모델의 버전 번호는 아니다.

기존 모델·리랭커 설정 선택에 사용한 질문과 분리한 **AI 작성 질문 80개**다.
사람의 질문 검수·장소 적합도 판정·모델 실행은 아직 하지 않았다. 정답이 완성된 골든셋이나
일반화가 검증된 결과로 소개하지 않는다. 기존 v1.4.0의 질문·정답·결과는 수정하지 않는다.

| 구분 | 문항 수 | 용도 |
|---|---:|---|
| 장소명 | 10 | 특정 장소 찾기 |
| 의미·취향 | 10 | 장소명을 말하지 않는 탐색 |
| 복합 조건·지역 필터 | 10 | 여러 요구와 지역 조건 |
| 부정·제외 표현 | 10 | query 안의 부정 의도. 제외 ID API 기능과 구별 |
| 오타·띄어쓰기·구어체 | 10 | 입력 잡음 |
| 다국어·언어 혼합 | 10 | 한국어 밖 표현의 탐색 |
| 근거에 민감한 조건 | 10 | 운영시간·가격·접근성 등의 확인 한계 |
| 코퍼스 범위 밖 요청 | 10 | 다른 지역·환경 등 범위 한계 |

처음 여섯 유형 60개만 기본 순위 평가 대상으로 삼는다. 뒤의 20개는 별도 도전 평가다.
각 유형 10개라는 균등 구성은 실제 사용자 요청 비율을 뜻하지 않는다. 이는 초기 평가 설계이며
80문항이라는 수가 통계적 검정력이나 일반화를 보장하지 않는다.

## 독립성의 범위

- 동결 코퍼스는 기존 서울 관광지 449곳과 같다. 새로운 장소·도시로의 일반화를 확인하는 셋이 아니다.
- 과거 질문 192개(중복 제거)와 정규화 완전 중복은 0개다. 문자 3-gram 유사도 검사 결과는 `manifest.json`에 있다.
- 이 검사는 의미 중복 부재를 증명하지 않는다. 기존과 겹치는 주제·장소도 있으며, 작성자는 기존 평가 구조와 코퍼스 범위를 알고 있다.
- 번역·오타·유사 의도끼리는 `source/families.json`에서 묶었다. 기본 60문항은 **19개 질문군**이다.
- 이 질문을 보고 모델이나 설정을 변경하면 독립 시험 역할이 끝난다. 변경 후 최종 검증에는 다시 새 질문이 필요하다.
- 질문 수정은 결과를 보기 전에 새 버전에서 한다. 부적합한 질문을 결과에 따라 골라 빼지 않는다.

## 파일

- `source/questions.csv`: 새 질문과 검색 API 필터. 정답 ID·추천 결과·모델 점수 없음.
- `source/families.json`: 관련 질문의 군집. 통계적 독립 표본으로 중복 계산하지 않기 위한 구분.
- `protocol.json`: 비교 설정, 평가 범위, 주지표, 누락 처리와 재사용 규칙.
- `rubric.md`: 사람 판정 기준. 공란·unknown을 오답으로 바꾸지 않는다.
- `manifest.json`: 질문·규칙·코퍼스·과거 질문 해시와 중복 검사 결과. 재동결로 덮어쓰지 않는다.

질문 CSV와 생성되는 검수 CSV는 Windows Excel이 한글을 인식할 수 있도록
**UTF-8 BOM**으로 저장한다. 다른 도구에서 읽을 때는 `utf-8-sig`를 사용한다.
2026-10-27에 질문 CSV의 누락된 BOM을 추가했다. 질문·필터·입력 내용 해시는 동일하며,
`manifest.json`에서는 CSV 파일의 바이트 해시만 갱신했다. 이전 manifest 해시는
`270eb3bed8983e9e12066a28a280da77d4212d6f30b3a2cc20dfa78d87b5e207`이다.

## 진행 순서

저장소 루트 PowerShell 기준이다. 아래 실행 결과는 동결 데이터셋 밖의 새 디렉터리에 기록한다.
기존 `search/run.py`와 `collect_live.py`의 v1.4 전용 빌더는 이 셋에 직접 사용하지 않는다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/search/holdout.py check
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/search/holdout.py export-inputs --output-dir Evaluation/runs/search/search-holdout-v1.0.0/input-review-01
```

1. `question_review.csv`를 사람이 읽는다. 명료성·번역·필터·원하는 평가 범위를 확인하고
   각 행의 `decision`에 `accept`, `reviewer`에 검수자 식별자를 적는다. 문항을 수정해야 한다면
   아직 결과를 보지 않은 상태에서 새 버전을 만든다. 원문과 달라진 검수표로는 수집하지 않는다.
2. 비교 설정은 `protocol.json` 값으로 고정한다. 배포된 모델 revision, GPU, 실제 환경변수,
   검색 후보 상한과 반환 수를 확인한다. DB의 ID·본문·벡터 모델이 동결 코퍼스와 일치하는지도 확인한다.
   이 확인은 수집기가 자동 증명하지 않는다. 확인한 값을 별도 `runtime.json`으로 기록한다.
   필수 키는 `embedding_revision`, `reranker_revision`, `gpu`와 boolean
   `corpus_verified`, `configuration_verified`다. revision에는 실제 설치된 값을 적는다.
3. 검수 이후 아래 수집기로 두 모드를 실행한다. 질문별 모드 순서를 교차하고 정답 점수를 계산하지 않는다.
   관리자 UID와 로컬 JWT 설정은 기존 수집기와 같은 방식으로 사용한다. 네트워크 실행은 아직 하지 않았다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/search/collect_holdout.py --question-review Evaluation/runs/search/search-holdout-v1.0.0/input-review-01/question_review.csv --runtime-record <RUNTIME_JSON> --admin-uid <ADMIN_UID> --output-dir Evaluation/runs/search/search-holdout-v1.0.0/collection-01
```

4. 실패·조건 미적용·동결 코퍼스 밖 ID가 있으면 먼저 원인을 확인한다. 실패를 정답 없음으로 취급하지 않는다.
   기존 API의 각 모드는 후보를 새로 검색하므로 이 수집은 **서비스 두 방식의 비교**다.
   리랭커 자체 효과를 분리하려면 동일 후보를 고정한 실험이 별도로 필요하다.
5. 두 방식의 상위 10개 합집합을 중복 제거하고 순서를 섞어 검수표를 만든다.

```powershell
.\.venv-ragas\Scripts\python.exe Evaluation/tracks/search/holdout.py prepare-review --embedding-records Evaluation/runs/search/search-holdout-v1.0.0/collection-01/embedding_records.jsonl --reranking-records Evaluation/runs/search/search-holdout-v1.0.0/collection-01/reranked_records.jsonl --output-dir Evaluation/runs/search/search-holdout-v1.0.0/blind-review-01
```

6. 검수자에게는 `candidates.csv`, `questions.csv`, `rubric.md`만 전달한다.
   `private_mapping.jsonl`, 원본 순위, 모드별 결과는 보여주지 않는다.
   모든 후보의 relevance·근거·판정 이유를 작성한다. 기존 질문의 정답을 새 질문에 복사하지 않는다.
7. 사람 판정과 이견 조정이 끝난 뒤 채점한다. 이 단계의 자동 최종 채점기는 아직 포함하지 않았다.
   현재 도구는 질문 검증·입력 수집·블라인드 검수표 생성까지만 제공하며 가짜 품질 결과를 만들지 않는다.

## 채점 시 고정할 해석

주지표는 관련 장소가 하나 이상 판정된 기본 문항의 NDCG@10이다. 동일 질문의 두 방식 차이를
계산한 뒤 질문군별 평균을 구하고, 질문군을 같은 가중치로 합산한다. 질문군 단위 paired bootstrap으로
95% 구간을 보고한다. 개별 문항 평균·유형별 결과·개선/동률/악화 건수도 함께 공개한다.
신뢰구간이 0을 포함하면 확실한 우위를 주장하지 않는다. 이 구간도 불완전한 라벨과 실제 트래픽 편향을 해결하지 않는다.

모든 상위 결과에 판정이 있어야 해당 문항의 완전 판정 비교를 한다. unknown·수집 실패·검수 누락의
건수와 유형을 공개한다. 관련 장소가 풀에 하나도 없으면 NDCG를 억지로 0점 처리해 주평균에 섞지 않고
해당 문항의 반환 행태를 별도로 보고한다. 상위 10개 풀 밖의 실제 정답은 아직 알 수 없으므로
Recall은 전체 정답 회수율이 아닌 **풀 안의 알려진 정답 기준**이다.

이 평가는 검색 결과를 평가한다. Agent의 응답·거절·명확화, 일정 생성, 실제 운영시간 보장은 별도 평가다.
