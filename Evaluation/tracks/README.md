# 트랙 실행과 구현 상태

모든 run.py는 check / export-inputs / evaluate를 제공한다.
evaluate는 저장된 응답을 채점하며 앱 API·도구·DB를 실행하지 않는다.
--split development/test/all을 반드시 지정하며 --type으로 기대 응답 타입을 좁힐 수 있다.

| 트랙 | 현재 대상 | 코드 검사 / GPT |
|---|---|---|
| search | 기존 검색 문항 85개 | 임베딩·리랭킹 순위에 동일 Top-1/5/10 및 여섯 순위 지표, judged@K |
| tool_call | 200개 | 도구 이름·스키마·고정 인자, 호출 P/R/F1. query 의미는 선택적 GPT |
| plan | 50개 | 선택 ID·조건·가상 시간·경로 비용. 설명은 선택적 GPT |
| state | 70개 | 미리보기·확정·관측 버전·비계획 데이터 보존 |
| memory | 20개 | 시나리오 기억 ID 순위, 일부 명시/추론 취향 관측. 최종 발화는 선택적 GPT |
| behavior | 45개 | 타입·기대 도구·상태와 선택적 GPT의 의도/금지 주장 검사 |
| persona | 기존 message 200개의 별칭 | 코드 형식 검사와 선택적 GPT의 기존 페르소나 기준 |
| message | 200개 | 코드 형식/도구 검사와 기존 네 가지 GPT 발화 기준 |
| end_to_end | 200개 | 저장된 전체 기록의 기존 채점기 조합. 실제 E2E 실행기는 아님 |

트랙은 문항과 출력 지표를 선택한다. 타입은 PLACES/PLAN/PLAN_DIFF/CLARIFICATION/TEXT의
클라이언트 응답 형식이다. 둘은 1:1 관계가 아니다. 특정 트랙에서도 GPT를 켜면 기존 네 가지
발화 기준을 적용하고, 적용 불가는 null로 남긴다. 새 가중치나 종합 점수를 만들지 않았다.

## 실제 구현된 파일

- search/score_ranking.py → common/metrics/ranking.py: 임베딩 전용과 리랭킹 후 순서를 동일 기준으로 계산
- tool_call/score_args.py: 도구 호출 정규화·이름/인자/스키마 비교
- plan/score_rules.py, score_route.py: 후보·조건·제공 비용 행렬의 경로/시간
- state/score.py: 실제 backend_observation 확인
- memory/score_extraction.py, score_retrieval.py: 기존 추출/확인 및 기억별 순위 검사
- end_to_end/score.py: 기존 코드 검사 조합
- common/judge/: 기존 GPT 메시지 평가, JSON 출력·근거 인용 검사

## 아직 없는 기능

실제 검색 API 수집과 두 전략의 자동 대조·지연 p50/p95, 오케스트레이터 1스텝 실행,
여러 턴 대화 재생·DB 기억 추출 실행, 실제 도로 비용 연동, V1.4 LangSmith 자동 게시,
V1.4 Ragas ID 전용 실행기와 후보별 place_relevance Judge는 미구현이다.
따라서 이 이름의 비어 있는 Python 실행 파일을 만들거나 완료로 표시하지 않았다.
