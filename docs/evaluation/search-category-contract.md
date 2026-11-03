# 검색 분류 계약과 실제 인자 회귀

이 문서는 최초 오프라인 수정 단계의 기록이다. 이후 승인된 기존 두 문항의 실제 검색 도구 연결 검증은 [완료 보고서](../../Evaluation/runs/contextual/openai-strict-search-two-case-v1/20261103-01/REPORT.md)에 별도로 확정했다. 아래 초기 단계의 미실행 설명을 현재 완료 범위로 확대 해석하지 않는다.

2026-11-03의 OpenAI strict 2문항 실행에서 `PLR-TM-palaces-03`은 `search_places`를 선택했지만 `category="궁"`을 추가했다. 검색 후보는 0개였다. 이번 수정은 검색 필터 선택 계약과 서버 검증을 맞추며, 응답 출력 형식은 변경하지 않는다.

## 허용값의 기준

현재 `TourPlaceIndexingService.toCreateCommand`는 `TourContentType.getLabel()`을 `places.category`에 저장한다. `PlaceSearchCategories`는 이 enum에서 허용값을 가져와 도구 스키마와 서버 검증에 함께 사용한다.

허용하는 저장 분류는 `관광지`, `문화시설`, `축제공연행사`, `여행코스`, `레포츠`, `숙박`, `쇼핑`, `음식점`이다. 보존된 v1.4.0 평가 DB 스냅샷 449행에서는 `관광지`만 관측됐다. 8개 모두가 현재 DB에 존재한다거나 DB에 SQL CHECK 제약이 설정됐다는 의미는 아니다. 운영 DB를 조회하거나 분류를 갱신하지 않았다. 추천용 `PlaceCategory`의 세부 분류는 이 저장 분류와 다른 체계다.

## 계약

- `category`는 위 저장 분류와 정확히 일치하는 문자열 또는 null이다. canonical 스키마에서는 생략할 수 있고, strict 스키마에서는 기존 방식대로 필수 필드에 null을 허용한다.
- 궁, 조용한, 왕실 가족의 거처 같은 장소 세부 유형·분위기·관계 조건은 `query`에 유지한다. 선택 분류를 확정할 수 없으면 생략 또는 null로 두며, 기존 `searchContext` 상속 규칙을 적용한다.
- 도구 인자와 상속된 조건의 잘못된 category는 검색 전에 거부한다. 직접 검색 API가 사용하는 요청 객체 경로와 기존 문자열 인자 경로에도 동일한 검증을 적용한다.
- 서버는 `궁`을 `관광지`로 바꾸거나, 잘못된 필터를 지우거나, query를 다시 작성하지 않는다. 이동 전용 규칙이나 단어별 보정표는 추가하지 않는다.

## 실제 원본과 회귀 범위

`Server/TravelMate/src/test/resources/search-category/openai-palaces-03.response.json`은 실제 제공자 응답을 바이트 그대로 복사한 자료다. `provenance.json`에 원본 해시·입력 해시·모델·실행 출처를 남겼다. 테스트는 이 응답의 실제 함수 인자 문자열을 읽는다.

오프라인 검사는 다음을 확인한다.

- 원본 제공자 응답의 해시 보존
- 저장 enum, canonical·strict 스키마 enum, 서버 허용값의 일치
- 허용 분류별 검색어와 필터의 원형 전달
- 잘못된 분류와 상속된 잘못된 분류의 거부 및 외부 검색 호출 차단
- 세부 특성을 포함한 query의 보존과 생략·null 필터의 비추론
- 실제 `category="궁"` 인자의 strict 거부 기록 및 canonical 실행의 실패 상태·원본 인자 보존·재시도 없음

오프라인 검증만 수행한다. 실제 API·모델·임베딩·검색·DB 호출과 기존 2문항의 자동 재시험은 수행하지 않는다. 이전 중계기 실패는 계속 모델 품질 집계에서 제외하며, 이번 수정이 실제 모델의 필터 선택을 개선했는지는 아직 재측정하지 않았다.

실행 결과: 신규 분류 계약 검사 21개와 관련 기존 검사 44개, 합계 65개 통과(실패·오류·건너뜀 0). 실행 명령은 다음과 같다.

```powershell
.\gradlew.bat --offline --no-daemon test --tests '*SearchCategoryContractTest' --tests '*SearchToolContractRegressionTest' --tests '*OpenAiStrictToolContractTest' --tests '*IndependentPlaceSearchTest'
```
