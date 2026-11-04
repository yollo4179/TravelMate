# LiLi 라우터 기본 평가 v2

`LILI_ROUTER_V1` 경로를 평가한다. LiLi가 근거 없이 먼저 반응하며 분기를 정하고, 서버가 도구를 실행한다. 검색과 계획은 작업으로 따로 실행된다.
v1(`conversation-smoke-v1`)은 단일 LLM 경로의 기록과 오프라인 회귀에 그대로 남긴다.
v2는 문항과 판정 범위가 달라서 v1 결과(이전 2/9, LiLi 첫 실측 8/9)와 직접 비교하지 않는다.

## v1에서 바뀐 것

| case ID | 변경 | 이유 |
|---|---|---|
| `CONV-SEARCH-exclude-first` | 기대를 `CLARIFY`로 변경 | 입력에 보이는 후보 목록이 없다(`history=[]`, `excludePlaceIds=[]`). 어떤 장소를 뺄지 되물어야 한다 |
| `CONV-SEARCH-exclude-shown` | 새 문항 | 같은 질문에 앱이 보여 준 목록(`displayedResult`)을 넣었다. 순번 → 장소 ID → 적용 필터 → 결과 제외를 모두 확인한다 |
| `CONV-PLAN-create` | `plan_outcome: DRAFT_COMPLETED` | 작업 접수와 초안 완성을 따로 판정한다. 실패나 시간 초과는 완성으로 보지 않는다 |

나머지 7문항은 v1과 같은 질문·입력 해시이고 `expected.lili_branch`만 쓴다.

## 순번 계약

- `displayedResult.placeIds`는 앱이 지금 보여 주는 추천 결과의 장소 ID를 화면 순서대로 담는다. `resultId`는 그 결과(추천 작업)의 ID다.
- "첫 번째"는 이 목록의 1번이다. 서버는 새 검색 결과로 순서를 추정하지 않는다.
- LiLi는 순번(`exclude_positions`)만 내고, 서버가 장소 ID로 바꿔 기존 `excludePlaceIds`에 합친다.
- 목록이 없거나 순번이 범위를 벗어나면 검색하지 않고 되묻는다.

`CONV-SEARCH-exclude-shown`의 목록은 실측 `20261104-lili-r2-rest`에서 "종로 관광지" 추천 작업(`fc4a7e8f-…`)이 실제로 반환한 순서다.
1번은 사직공원(서울)(173)이다.

## 판정

- 제외 문항: 아래를 모두 확인한다.
  - LiLi 순번이 `[1]`인지
  - 서버가 변환한 ID가 `[173]`인지
  - 작업 검색 조건 `searchCriteria.excludePlaceIds`에 173이 있는지
  - 작업 결과에 173이 없는지
- 계획 생성 문항: 아래를 각각 기록한다.
  - `plan_job_accepted`: 접수
  - `plan_job_succeeded`: 작업 완료
  - `plan_draft_retrieved`: 초안 조회
  - `plan_draft_dialogue`: 대사 컷
  - 초안 완성까지 통과해야 문항이 통과한다.
  - 생성 응답 본문과 실패 사유는 `PLAN_DRAFT` 이벤트로 작업에 연결된다.
- 모든 LiLi 대사: 내부 코드·용어(영문 상태 코드, 토큰·예산 등)가 없어야 한다.
- 추천 대사: 근거 원문이 없는 후보의 이름을 쓰지 않아야 한다.

채점기는 `Evaluation/tracks/conversation/lili_score.py`다.
