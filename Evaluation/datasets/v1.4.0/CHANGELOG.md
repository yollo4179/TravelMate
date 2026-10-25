# V1.4.0

- 단일 LLM이 일정 도구를 호출한다는 평가 명세를 명시했다. 기존 폴더명·200문항·분할·점수 기준은 유지한다.
- 사용자 지정 루트 Evaluation/V1.4.0 아래 common/plannerLLM/managerLLM을 구성했다.
- 단일 대화·제어 LLM의 기능별 평가로 각 100문항을 작성했다. 공통 200문항에 reference와 expected_response_type을 기록했다.
- PLACES/PLAN/PLAN_DIFF/CLARIFICATION/TEXT 타입별 뷰와 다중 evaluation_tracks 뷰를 공통 원본에서 생성한다.
- v1.3.0 관광지 스냅샷·질문별 사람 판정·검수 메모는 바이트 단위로 보존했다. 새 기능 기대값은 사람이 검수했다고 표시하지 않았다.
- 코드 검사는 타입·서버 data 보존·도구 스키마와 고정 인자·장소 선택·제공된 동선 비용·확정 및 실제 상태를 구분한다.
- 메시지·자유문장 query·페르소나·기억 활용은 선택한 gpt-4.1-mini와 역할별 MD로 별도 평가한다.
- 모델 입력과 정답·비공개 기억 픽스처를 분리했다. 고정 입력 해시가 다른 응답은 점수에 섞지 않는다.
- 원본과 생성 뷰 재생성은 실행 응답·results를 초기화하지 않는다.
- 실제 Agent·도구 API나 모델 성능 측정을 완료했다는 의미가 아니다.

## 디렉터리 분리 (2026-10-26)

- datasets/source·generated·rubrics, common, tracks, runs, tests로 책임을 나누었다.
- 기존 문항·골든셋·판정·루브릭과 과거 버전 파일을 보존했다.
- 트랙별 실행 명령, 결과 덮어쓰기 방지, 실행 이력·최신 참조를 연결했다.
- 실제 API 수집 등 미구현 항목은 tracks/README.md에 구분했다.
