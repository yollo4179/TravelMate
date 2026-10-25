# 추천·계획 평가 뷰

단일 대화·제어 Agent의 추천·장소 선택·계획 도구 결과를 평가하는 100문항이다.
별도 Planner 모델의 존재를 전제로 하지 않는다.

현재 타입 구성은 PLACES 80문항·PLAN 20문항이다. 다른 타입의 생성 뷰는 빈 파일일 수 있다.

- 원본: ../common/cases.source.json
- 정답 뷰: golden.jsonl, development.jsonl, test.jsonl, by_type/
- 코드 검사: ../common/metrics.py
- 메시지·검색 query 의미의 GPT 기준: rubric.md
- 실행: run.py check / export-inputs / evaluate

수정은 공통 원본에서 한다. by_type은 정답지를 따로 관리하기 위한 복사본이 아니라
공통 원본에서 생성한 읽기용 뷰다. 자세한 실행·응답 레코드 계약은 [루트 문서](../README.md)를 따른다.
