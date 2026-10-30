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
