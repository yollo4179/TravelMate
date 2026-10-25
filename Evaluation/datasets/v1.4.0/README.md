# 단일 Agent 골든셋 v1.4.0

장소 검색·일정 생성·수정 도구를 호출하는 대화·제어 LLM 하나를 평가한다.
[전체 실행 방법](../../README.md)과 [도구 평가 명세](TOOL_EVALUATION.md)를 참고한다.

| 위치 | 역할 |
|---|---|
| source/cases.source.json | 수정하는 원본 200문항. 기억·페르소나·도구·상태 기대값 포함 |
| source/corpus.source.json · snapshot.json | 동결한 449개 관광지와 DB 스냅샷 |
| source/source_goldenset_v1.3.0.jsonl · review_notes.csv | 기존 질문별 장소 판정·사람 검수 보존 |
| source/persona/guide_v1.json | 성격·관계·말투·경계 예시 |
| source/judge_config.json | 기존 GPT 평가 모델 설정 |
| generated/golden.jsonl · development.jsonl · test.jsonl | 전체 200·개발 160·시험 40문항 |
| generated/corpus.json | 동결 코퍼스 원본에서 생성한 조회 파일 |
| generated/by_type/ | PLACES 85·PLAN 29·PLAN_DIFF 19·CLARIFICATION 20·TEXT 47 |
| generated/by_track/ | search·tool_call·plan·state·memory·behavior·message·persona |
| generated/by_group/ | 이전 100+100 문항 묶음의 호환 조회 뷰. 모델 두 개가 아님 |
| generated/schemas/ | 응답·도구 인자·수집 레코드 계약 |
| rubrics/plan_quality.md · behavior.md | 원래 두 문항 묶음의 GPT 기준을 내용 변경 없이 보존 |
| manifest.json · validation.json | 원본·생성물·계약·루브릭의 해시와 검증 상태 |

persona 뷰는 기존 message 문항의 별칭이다. 페르소나 기준은 어느 응답 타입에도 적용할 수 있다.
TEXT만 볼 때는 --type TEXT를 명시한다. 원본 트랙 태그나 평가 문항을 이동 중 추가하지 않았다.
기억 검색은 시나리오별 기억 ID를 정답으로 쓰며 관광지 판정표를 재사용하지 않는다.

reference는 200문항의 발화 예시다. 검색·도구 인자 코드 채점은 이를 읽어 비교하지 않는다.
기존 사람 검수는 보존했으며 새 기능 기대값은 AI 작성 초안임을 계속 명시한다.
미판정 장소는 확인된 오답이 아니다. Recall은 알려진 정답에 대한 값이며 judged@K를 함께 본다.

순서·시간 검사는 가상 비용 행렬 기준이며 실제 도보 시간·운영시간을 입증하지 않는다.
현재 일정 픽스처의 상한 6개는 평가용 경로 계산 범위이며 운영 서비스 한도를 정한 것이 아니다.
modify_plan의 재정렬 목적 위치와 명시적 롤백 도구 계약 등은 후속 제품 설계가 필요하다.

빌드는 generated/와 manifest.json·validation.json만 다시 쓴다. source/·rubrics/·runs/는 쓰지 않는다.
실제 응답과 점수는 이 디렉터리에 저장하지 않는다. 코드는 ../../common/ 및 ../../tracks/에 있다.
과거 source_dataset 경로와 evaluation_group은 원본 이력을 보존하기 위해 그대로 유지했다.
