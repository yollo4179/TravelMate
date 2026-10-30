# 장소 수집·청크 추적 자료

실제 자료는 `<place_id>_<장소명>/` 아래에서 관리한다. 이 디렉터리의 장소별 원문과 생성 응답은
개인정보·외부 저작물·사용량 정보가 포함될 수 있어 `.gitignore`로 제외하며, 별도 런타임 볼륨에서 보존한다.

`requests/`에는 원문·요청·응답·검증된 청크, `index-inputs/`에는 색인 전 모든 후보 원문/청크,
`references/`에는 여러 장소가 공유한 원문 아카이브의 위치를 기록한다.
실제 수집 자료처럼 보이는 가짜 장소 리뷰 파일을 커밋하지 않는다.

[실행·공통 형식·DB 변경](../docs/specifications/contextual-retrieval.md)

프롬프트: [v1 기준 버전](../embedding-server/app/contextual/prompts/v1_contextual_prompt.py) ·
[v2 기본 버전](../embedding-server/app/contextual/prompts/v2_contextual_prompt.py).
같은 입력으로 비교할 때는 [명세의 baseline 실행](../docs/specifications/contextual-retrieval.md#같은-입력으로-프롬프트-비교)을 사용한다.

로컬 Sonar 실행 9개는 [v1_local_2d365e87c12314cb 프로필](../embedding-server/app/contextual/profiles/v1_local_2d365e87c12314cb.json)로 등록했다.
`--baseline-record`와 `--baseline-profile v1_local_2d365e87c12314cb`를 함께 지정하면
기존 원문·effort·출력 한도·응답 스키마를 그대로 두고 v2 지시문만 비교할 수 있다.
표준 v1 검증을 완화하거나 원본 기록을 다시 쓰지 않는다. 기본은 과금 없는 미리보기이며
실제 호출은 `--execute`를 붙일 때만 수행한다. 새 결과는 프로필/프롬프트별 요청 경로에 보존한다.
[실행 방법과 비교 조건](../docs/specifications/contextual-retrieval.md#로컬-sonar-실행-9개를-재사용하는-비교)
