# 단일 LLM의 도구 사용 평가

대화·제어 LLM 하나가 사용자 의도를 해석하고 도구와 인자를 선택한다.
장소 검색, 일정 생성, 일정 수정은 서버 도구다. 별도의 계획 LLM은 두지 않는다.
LLM은 장소 ID를 선택할 수 있지만, 일정의 순서·시간·동선 계산과 저장은 서버 책임이다.
가이드 캐릭터와 일상 대화도 같은 LLM이 처리한다.

```text
발화 + 대화/기억/현재 상태
  → 단일 LLM의 도구 선택과 인자
  → 서버의 인자 검증·도구 실행
  → 서버의 type/data + LLM의 message
```

## 골든셋과 실제 기록의 비교

| 평가 대상 | 골든셋 기준 | 실제 관측값 | 채점 |
|---|---|---|---|
| 도구 선택·인자 | expectations.tool_call | tool_calls | 도구 이름·스키마·고정 인자 비교. 자유문장 query의 의미는 GPT 기준 |
| search_places | 질문별 place_judgments | PLACES의 장소 ID와 순서 | Top-1·Top-K, Precision·Recall·F1·MAP·MRR·NDCG, 미판정 포함 여부 |
| create_plan | expectations.plan 및 고정 후보·조건·비용 행렬 | 필터 전 선택 ID, 반환 stops·시간 | 장소 선택과 서버 일정 계산 결과를 분리해 검사 |
| modify_plan | 기대 변경·현재 일정·확정 여부 | tool_calls, PLAN_DIFF, backend observations | 대상·작업·미리보기·확정·실제 반영 버전 검사 |
| ask_clarification | 기대 도구·missing 필드, 행동 기준 | 도구 인자·CLARIFICATION·message | 빠진 항목과 확인 질문의 적절성 |
| recall_memory·기억 사용 | 시나리오별 정답 기억 ID·기억 정책 | 조회 ID·도구 요약·추출값·저장 관측값 | 기억 검색, 추출/저장, 최종 발화 근거를 각각 검사 |
| 최종 응답 | expected_response_type·행동 기준·페르소나 | response 및 주 도구 결과 | type·data 보존은 코드, 발화의 의도·근거·성격은 GPT |

서버 도구의 계산 오류와 LLM의 선택 오류를 하나의 모델 점수로 합치지 않는다.
도구가 실패했을 때 실패를 정확히 설명한 응답은 실패를 성공으로 꾸민 응답과 구분한다.
실제 저장·버전 등 관측값이 없으면 해당 검사는 null이며, 저장 성공으로 추정하지 않는다.

## reference의 역할

검색과 도구 호출의 코드 채점은 문장형 reference를 사용하지 않는다.
검색 정답은 질문별 장소 관련도이고, 도구 호출 정답은 도구 이름과 구조화된 인자다.
되묻기·답변 보류는 기대 행동과 금지 주장으로 판단한다.

현재 200문항의 reference는 최종 발화의 예시로 유지하며, 유일한 정답 문구를 뜻하지 않는다.
선택적인 GPT 메시지 평가에는 이 예시와 역할별 루브릭을 전달한다.
현재 데이터셋 빌더는 모든 문항에 이 필드가 있는지도 검사하지만,
문장형 reference가 검색·도구 지표의 계산 근거라는 뜻은 아니다.
GPT 메시지 평가를 실행하지 않아도 코드 채점은 가능하다.

## 파일과 실행기

- 작성 원본: source/cases.source.json
- 타입별 정답 뷰: generated/by_type/
- 관점별 정답 뷰: generated/by_track/의 search·tool_call·plan·state·memory·behavior·message
- 코드 채점기: ../../tracks/end_to_end/score.py 및 ../../tracks/별 채점 모듈
- 발화 채점기: ../../common/judge/runner.py와 rubrics/의 버전별 기준
- 기록 평가 실행기: ../../tracks/*/run.py

plannerLLM과 managerLLM이라는 기존 100+100 문항 묶음은 generated/by_group에만 보존한다.
실행 진입점은 search·tool_call·plan·state·memory·behavior·persona·message·end_to_end 트랙이다.
여러 관점의 평가에는 같은 문항을 연결할 수 있고, 원본과 분할은 공통으로 유지한다.

현재 실행기는 이미 수집한 응답을 채점한다. 실제 LLM/도구를 호출하는 수집기나
서버 오케스트레이터를 구현한 것은 아니다. 이 문서는 평가 대상과 기록 계약을 명시하며,
새로운 운영 도구·평가 문항 수·평가 모델·가중 종합 점수를 추가하지 않는다.
