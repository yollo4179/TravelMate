# 핵심·보조 관계의 독립 보존 코드 검증

문서 버전: 1 · 작성: 2026-11-01 · 기준: `1b62e006` · 브랜치: `fix/contextual-supporting-relations`

**경관·시설의 subject와 이동의 endpoint를 분리하고 primary/supporting 관계를 보존·검색하는 코드를 구현했다.**
이번 검증은 합성 응답·모의 SQL 전달·기존 기록 읽기만 사용했다. 실제 Sonar 생성·DB 적용·검색 성능 개선의 검증이 아니다.
기존 v6의 자동 4/5와 검수 후 선택 5/5 기록은 변경하지 않았다.

## 변경

- 새 선택 계약 `contextual-independent-relations-v7`와 `contextual-validation-v4`를 추가했다. 기본값은 계속 v2다.
- 관계의 `type=movement`, `importance=primary|supporting`, `evidence={start,end,quote}`를 필수로 받는다.
- content_kind는 주된 관찰 종류다. landscape/facility/other에서도 관계를 저장하며 endpoint를 subject와 같게 강제하지 않는다.
- 관계 evidence는 같은 청크 내 정확한 원문 구간이다. 조건 인용도 그 관계 근거 안에 있어야 한다.
- 같은 원문·청크는 한 번 저장하며 장소별 활성 슬롯만 subject/relation_endpoint로 구분한다. DB trigger·초기화 SQL도 이를 반영했다.
- 경관·시설·일반 검색은 subject 슬롯만, 이동 검색은 양쪽 슬롯과 실제 endpoint를 사용한다. 비중 필터를 생략하면 핵심·보조를 모두 찾는다.
- 이동 리랭킹 입력과 description은 선택한 이동 절만 사용한다. 보존용 전체 원문·place_refs에는 손대지 않고 retrieval_scope/matched_relations/search_text를 추가한다.
- 목적지의 기본 장소 벡터에는 목적지 subject 근거 또는 목적지의 기본 설명을 사용해 출발지의 경관 벡터가 대체하지 않게 했다.
- 관계만 명확하고 subject가 없는 경우도 알려진 endpoint가 있으면 관계 전용 후보로 보존한다. 검수 승인과 장소별 20개 상한은 유지한다.

## 요청한 합성 회귀 사례

원문: “A공원은 야경이 아름답고, 관람 후 B공원으로 걸어갈 수 있다.”

한 청크의 content_kind는 landscape, A는 subject, B는 mentioned다.
A→B의 importance는 supporting이며 근거는 “관람 후 B공원으로 걸어갈 수 있다.”다.

| 검색 기준 | 기대·확인 결과 |
|---|---|
| landscape | A만 일치, B는 제외 |
| destination=B | 출발지 A만 일치 |
| origin=A | 목적지 B만 일치 |
| importance=supporting | A/B의 관계 참가자를 조회 가능 |
| importance=primary | 이 보조 관계는 제외 |
| movement | 주된 종류가 landscape여도 관계를 조회 가능 |

[합성 검사 결과](regression-check.json)에 실제 코드의 일치 결과와 B용 이동 검색 입력을 기록했다.
이는 고정 응답을 파싱한 코드 계약 검사이며 모델이 스스로 이렇게 판단했다는 결과가 아니다.

## 테스트와 호환성

- 서버: 101개 중 **90개 통과, 환경 통합 11개 미실행**. 평가 검사 **9개 통과**.
- 새 회귀 검사 10개: 혼합 원문 유지, 두 중요도·종류, 관계 전용 후보, 양방향 검색, 귀속 오염 방지,
  잘못된 ID/이름/위치/인용/비중 거부, 역할별 활성화, 모의 apply·검수·무료 재검증, 기존 스키마, 두 검색 단계의 SQL·입력 범위를 확인했다.
- 실제 PostgreSQL SQL·trigger 실행은 **0회**다. 쿼리 생성과 파라미터 전달은 모의 연결로 확인했다.
- 기존 v5 기록 9개, v6 기록 2개를 현재 코드로 읽었다. v5 보존 파일 63개와 v6 보존 파일 50개의 해시가 일치했다.
- v1~v6 지시문 및 기존 응답 스키마를 변경하지 않았다. v6→v7 스키마 변경은 프롬프트 전용 비교에서 거부한다.
- v6의 비중 없는 관계는 그대로 둔다. 기본 방향 검색은 유지하지만 primary/supporting을 새로 판정한 것으로 표시하지 않는다.
- [호환·보존 검증](compatibility.json) · [파일 해시](publication.json).

재현 명령:

```powershell
python -X utf8 -m unittest discover -s embedding-server/tests
python -X utf8 -m unittest Evaluation.tracks.contextual.test_score Evaluation.tracks.contextual.test_multi
python -X utf8 -m Evaluation.tracks.contextual.supporting_relations --output <새-결과.json>
```

## 실행하지 않은 것과 한계

이번 유료 API 호출 **0회**, DB 조회·쓰기 **0회**, BGE·리랭커 실제 검색 실행 **0회**, 배포·재시작 **0회**다.
SQL 파일 수정은 운영 반영이 아니다. 실제 적용에는 새 역할 제약·trigger 적용과 명시적 검수·재색인이 필요하다.
기존 데이터의 중요도를 자동 보완하거나 모델을 다시 호출하지 않았다.

- 실제 v7 Sonar의 중요도·관계 근거·귀속 정확성은 미검증이다. 정확한 인용이 의미·방향의 정확성까지 보장하지 않는다.
- 관계 검색 후보를 고르는 임베딩은 아직 전체 문맥+원문이다. 이동 절만 따로 임베딩하는 구조와 검색 성능은 이번 범위가 아니다.
- 자연어 조건 자동 선택·Spring/LLM 도구·UI 전달은 아직 연결하지 않았다. 명시적 관찰·관계 필터에 대한 워커 구현이다.
- 응답의 전체 보존 원문과 관계용 search_text를 구분해야 한다. 이를 무시하고 전체 청크를 목적지 특성으로 사용하는 상위 코드까지 검증한 것은 아니다.
- 검증 오류 관계가 있는 구간은 전체 후보를 격리해 원본과 오류 사유를 보존한다. 유효 관찰·관계의 부분 승인·부분 복구는 지원하지 않는다.
- 승인한 청크의 관찰·관계를 함께 적용하며, 적용 대상 endpoint도 READY·최신 버전·지문 검사를 받는다.
- 장소별 상한 20개는 관찰과 관계가 함께 사용한다. 최신 번들 교체 정책이므로 전체 유지 자료를 함께 적용해야 하며, 전체 유효 근거 보존은 미확인이다.
