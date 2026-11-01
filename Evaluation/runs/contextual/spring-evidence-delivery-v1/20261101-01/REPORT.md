# 검색 원문 근거의 Spring·계획 LLM 전달 검증

2026-11-01. 기준 커밋 `15d3d740`의 구조 점검에 이은 1단계 구현이다.
Kafka 모의 결과의 선택 원문이 Spring DTO와 기존 계획 LLM 요청에 보존되는지 검증했다.
단일 LLM 도구 루프·일정 수정·계획 검증 공통화·실제 검색/계획 품질 평가의 완료 보고가 아니다.

## 변경

경로는 `evidence_chunks → PlaceSemanticSearchClient.parseResults → PlaceSemanticSearchResult.evidenceChunks → PlaceSearchResponseDto.evidenceChunks`다.
원래 문서 전체를 보존하는 `SearchEvidenceChunk` 값을 사용해 원문·metadata·출처 ID/version·청크/문맥 버전·좌표·장소 귀속·관계·조건을 유지한다.
근거가 없는 구버전 메시지는 빈 목록으로 호환한다. 존재하는 근거의 잘못된 인용/형식은 실패로 처리하며 조용히 삭제하지 않는다.

`ContextPlanningService`는 선택 근거가 있는 검색 결과도 promptFactory에 전달한다.
후보 description의 400자 요약과 별도로 **전체 원문**을 구조화해 보낸다.
원문은 `original`, 장소 귀속·관계·조건은 `annotations`, 생성 보충 문맥은 `generatedSupplement`, 검색 표현/범위는 `retrieval`로 구분한다.
검색되지 않은 필수 장소는 근거를 창작하지 않고 `NONE_SELECTED`로 표시한다.
선택 근거가 있는 경우에도 `SELECTED_UNASSESSED`이며 의미 검증 성공으로 표시하지 않는다.

기존 LlmClient를 그대로 사용하고 입력 지침을 보완했다. 분위기·주차·시설·방문 조건·연결 설명을 원문에 기대어 작성하고,
부족·부정·상충·과거 기록을 현재 사실로 바꾸지 않도록 지시한다. 별도 판정 모델·이동 의도 정규식은 추가하지 않았다.
이 지침을 실제 모델이 얼마나 지키는지는 이번 모의 회귀로 판정하지 않는다.

## 소속 검증과 의미 판정의 구분

GeneratedPin의 선택형 citations는 `{evidenceId, sourceId, quote}`다.
실제 요청에 직렬화한 근거 집합에 ID가 있는지, 해당 pin 장소에 전달한 근거인지, source_id와 원문 인용이 맞는지 검사한다.
관계 범위의 근거는 선택된 관계의 원문 인용에 제한한다. A의 관찰을 B의 관계 근거인 것처럼 인용하는 구조적 오용을 거부한다.
원문 위치는 Python Unicode code point 단위로 검사하며 Java UTF-16 문자 수와 혼동하지 않는다.

출처가 맞아도 그 출처를 붙인 설명이 의미적으로 맞는지는 별개다.
본문의 자유문장 ID를 출처로 해석하지 않고 구조화 citations만 검사한다. 인용이 없는 기존 출력도 호환하므로 모든 설명의 인용 충족률을 보증하지 않는다.
근거가 부족하다는 사실을 장소 자체의 부적합 판정으로 바꾸지 않는다.
잘못된 구조화 인용은 저장 전에 실패시키지만 공통 계획 상태·시간·카테고리 검증 정책은 바꾸지 않았다.

## 모의 회귀 실행

명령은 선택한 **단위 검사만** 실행한다. `@SpringBootTest`의 실제 DB/임베딩/LLM 통합 검사는 실행하지 않았다.

```powershell
cd Server/TravelMate
.\gradlew.bat --offline test --tests com.yollo.TravelMate.SearchEvidencePipelineTest --tests com.yollo.TravelMate.ContextPlanPipelineTest --tests com.yollo.TravelMate.PlanContextContractTest --console=plain
```

컴파일 성공. **11개 통과·실패 0·건너뜀 0**이다. 새 근거 전달 검사 7개와 기존 계획 입력/검증 검사 4개를 포함한다.
이는 서비스 전체 테스트 수나 검색·답변 정답률이 아니다. [tests.json](tests.json)

| 검사 | 확인한 범위 |
|---|---|
| 모의 Kafka 완료 이벤트 | 실제 receiveResult·parseResults 사용. JDBC/트랜잭션은 모의여서 실제 DB를 쓰지 않음 |
| 검색 응답 DTO | 전체 evidence JSON·추가 metadata·출처·순위·점수가 보존되고 외부 JsonNode 수정이 원본에 영향을 주지 않음 |
| 400자 뒤의 조건 | 이모지가 있는 긴 원문 뒤의 과거/부정 조건과 별도 공사 차단 기록이 LLM 입력에 유지됨 |
| 원문/문맥 구분 | 생성 문맥은 별도 필드이며 원문으로 인용하면 거부 |
| 인용 무결성 | 잘못된 quote·좌표·선택 관계, 없는 근거 ID/출처 ID, 다른 장소의 근거 인용을 거부 |
| 관계 귀속 범위 | B의 관계 근거로 받은 청크에서 A의 야경 관찰 인용을 거부. 관계 원문은 허용 |
| 기존 계획 서비스 | Kafka에서 파싱한 결과를 실제 runGeneration에 주입. 기존 LlmClient의 모의 generate 요청에 전체 원문·조건이 포함됨 |
| 저장 경계 | 유효한 인용은 기존 후보·정규화·저장 인자를 유지. 잘못된 인용은 save 미호출 |
| 근거 없는 결과 | 빈 근거 목록·기존 출력 호환. 새 출처/인용을 만들지 않음 |

단위 fixture는 이전 이동 통제 사례의 성공/차단 표현과 전달 계약의 긴 원문·Unicode 상황을 사용한다.
새 여행 평가 문항이나 정답표를 만든 것이 아니며, 기존 v1.4.0/contextual 평가 문항을 새로 검색하거나 모델에 보내지 않았다.

## 유지한 동작

Python 검색·리랭킹·원문 좌표 계산·활성 선택은 수정하지 않았다.
검색의 순위·거리·활성 20개·후보 30개·반환 상한·기본 근거 수는 그대로다.
Spring 검색 인자와 계획 후보 ID/병합 순서, 기존 체류시간/카테고리 검사, 정규화·저장 호출을 유지했다.
계획 repository·DB 스키마·직접 초안 저장·모델 설정 파일도 바꾸지 않았다. [invariants.json](invariants.json)

검증용 citations는 저장 전 입력 소속 검사에만 사용한다. 기존 저장 형태를 유지하므로 인용을 새 DB 필드에 영속화하거나 UI로 반환하는 기능은 없다.
사용자 로컬의 미커밋 검색 수집기·평가기 확장은 존재하는 것으로 계속 구분하며 덮어쓰거나 이번 커밋에 섞지 않았다.

## 실행하지 않은 것과 한계

실제 검색·임베딩·리랭커·계획 LLM·판정 LLM·유료 호출·운영 DB 반영·배포는 **모두 0회**다.
Gradle은 기존 캐시와 `--offline`을 사용했다. 모의 호출 기록이 실제 모델 호출의 증거는 아니다.

전체 원문·metadata 때문에 LLM 입력이 길어질 수 있다. 기존 context/token 설정을 유지했고 실제 토큰 예산·품질·지연은 측정하지 않았다.
요청 문자열의 보존을 확인한 것이며 모델 서버 내부에서 긴 입력을 처리하는 방식까지 검증하지 않았다.
상한 밖/미선택 근거와 잘못된 장소 귀속을 복구하지 않는다. 인용 위치 일치가 출처의 외부 진위·현재성·의미 적합성을 보증하지도 않는다.

계획 검증 공통화에서 초안과 확정을 구분하는 작업은 다음 단계다.
단일 LLM의 도구 정의/tool_calls/도구 결과 누적/종료 루프, 일정 수정·확인·버전·롤백, 실제 이동시간·동선 최적화는 여전히 미구현이다.
실제 의미 평가를 실행할 때는 기존 데이터셋·case ID·문항 수·모델·반복·비용 범위를 먼저 확정한다. 이번 작업에서 새 평가 범위를 선택하거나 실행하지 않았다.

전달 계약은 [아키텍처 문서](../../../../../docs/architecture/search-evidence-delivery.md), 코드·자료 해시는 [publication.json](publication.json)에 있다.
