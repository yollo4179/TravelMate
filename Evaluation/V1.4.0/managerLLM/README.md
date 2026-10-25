# 일상·캐릭터·제어·기억 평가 뷰

같은 Agent의 일상 대화·페르소나·도구 연결·변경 미리보기·기억 활용을 평가하는 100문항이다.
plannerLLM 폴더와 다른 모델을 만들거나 비교하라는 의미가 아니다.

현재 구성은 TEXT 47·CLARIFICATION 20·PLAN_DIFF 19·PLACES 5·PLAN 9문항이다.
변경 미리보기와 사용자 확정 후 반영 결과, 버전 충돌·도구 실패를 구분한다.

- 원본: ../common/cases.source.json
- 정답 뷰: golden.jsonl, development.jsonl, test.jsonl, by_type/
- 코드 검사: ../common/metrics.py
- 대화·기억·도구 결과 설명의 GPT 기준: rubric.md
- 실행: run.py check / export-inputs / evaluate

가상 기억·현재 계획·최근 대화는 고정된 테스트 픽스처다.
실제 사용자 DB를 열람했다는 뜻이 아니다.
자세한 실행·응답 레코드 계약은 [루트 문서](../README.md)를 따른다.
