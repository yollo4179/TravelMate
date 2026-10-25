# 공통 원본·계약·평가기

cases.source.json은 200문항의 유일한 작성 원본이다.
기존 질문별 장소 판정과 검수 기록은 source_goldenset_v1.3.0.jsonl, source_review_notes.csv에 보존한다.
corpus.json과 snapshot.json은 원래 관광지 스냅샷과 바이트가 같다.

build_dataset.py --build는 정답 뷰만 생성한다.
build_dataset.py는 원본·뷰·분할·타입·참조 답변·공통 manifest를 읽기 전용으로 검사한다.

타입은 PLACES / PLAN / PLAN_DIFF / CLARIFICATION / TEXT다.
tool_call·search·plan·state·memory·behavior·message는 평가 관점이며 한 문항이 여러 관점에 속한다.
응답 타입과 평가 트랙은 같은 개념이 아니다.

프롬프트용 페르소나는 persona/guide_v1.json에 성격·관계·말투·경계 상황 예시를 버전으로 둔다.
실제 앱의 토큰 예산·기억 개수·도구 반복 한도를 이 평가 버전에서 결정하지 않는다.

규칙 검사와 GPT Judge는 각각 metrics.py, judge.py다.
results의 이름으로 가상 성능 점수를 미리 넣지 않는다. 실제 응답 레코드가 있어야 채점한다.
