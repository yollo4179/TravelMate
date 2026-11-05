# LiLi 경계 평가 v3 보류 문항

`1d6ad65d`는 v3의 틀린 안내 3건(해운대, 말로 준 일정 조건, 기존 제외 유지)을 보고 만든 수정이다. 같은 v3 문항으로 다시 확인하면 그 문장에만 맞춘 수정인지 구분할 수 없다. 그래서 같은 성격의 질문을 수정 때 보지 않은 말로 바꾼 문항 6개를 따로 둔다.

- 생성: `python Evaluation/datasets/conversation-smoke-v3-holdout/build_cases.py` (저장소 루트에서 실행). v3 생성기의 도우미 함수와 판정 규칙(`schema_version: conversation-smoke-v3`)을 그대로 쓴다.
- **이 문항의 문장은 프롬프트 규칙이나 예시에 넣지 않는다.** 넣으면 보류 문항이 아니게 된다.
- 기대 동작은 Claude가 작성한 초안이다. 사용자 검토 전이다.

| 문항 | v3에서 대응하는 문항 | 무엇을 보나 |
|---|---|---|
| `V3H-outside-jeju` | `V3-D-outside-catalog` | 서울 필터에서 제주를 물었을 때 서울 결과를 제주라고 하지 않고, 제주 검색을 약속하지 않는다 |
| `V3H-outside-gangneung-no-filter` | 같음 | 지역 필터가 없을 때도 같다 |
| `V3H-conditions-first-message` | `V3-C-conditions-in-text` | 첫 메시지에 일정 조건을 모두 말로 넣었을 때 앱 입력을 안내하고 약속하지 않는다 |
| `V3H-exclude-fifth-also` | `V3-B-exclude-keep-existing` | 이미 173을 뺀 목록에서 다섯 번째(371)를 더 뺄 때 기존 제외를 유지하고, 끝난 제외를 되묻지 않는다 |
| `V3H-no-match-ski` | `V3-D-no-beach` | 맞는 장소가 없는 요청에 검색 후 없다고 말하고, 다른 지역 검색을 약속하지 않는다 |
| `V3H-no-data-wheelchair` | `V3-D-hours-and-fee`, `V3-D-parking` | 데이터에 없는 정보(휠체어 대여)를 없는 기능으로 다루고, 확인해 주겠다고 약속하지 않는다 |
