# 공통 대화 경로: 구현과 오프라인 검증

구현 커밋은 `fcfbb48e`다. 코드 기준·설정·입력·원본 응답·이벤트·기계적 판정을 이 폴더에 보존했다.
**MOCK 9사례가 기계적 검사를 통과했으며 실제 모델 품질 성공은 0건이다.** 새 서버 배포나 실제 모델/검색을 실행한 결과가 아니다.

| 확인 | 결과 |
|---|---|
| 서버 관련 모의 회귀 | 157개 통과 |
| 대화 평가기·공통 모듈/실행기 | 27 + 23 = 50개 통과 |
| 검색 관련 Python | 141개 통과·DB 통합 32개 건너뜀 |
| 별도 검색 모듈 2개 | 호스트 torch/asyncpg 부재로 미실행 |
| Node 클라이언트 계약 | 7개 통과 |
| Vite 빌드 | 통과 |
| Chromium | 대화·추천·계획 접수·완성 초안 표시, 모의 요청 4개, 외부 요청 0개 |
| 9사례 통합 MOCK | 기계적 9/9, 실제 품질 0/9, all_quality_passed=false |
| 실제 OpenAI·계산·Perplexity·검색·judge | 모두 0회 |
| 운영 DB 변경·배포 | 없음 |

이 수치를 전체 회귀 완료로 해석하지 않는다. 기존 Evaluation 전체 검사 중 SDK MockTransport 대기가 지속돼 중단한 사실도 기록했다.
초기 브라우저 검사에서 작업 상태 버튼 누락을 발견해 수정한 뒤 네 UI 상태를 다시 확인했다. 모델 실패로 집계하지 않는다.
컨테이너를 이용한 보조 검사 시도는 경로·권한·의존성 문제로 완료하지 못했고, 통과 수에서 제외했다. 임시 검사 이미지는 삭제했다.

`run.json`의 evaluator_git_sha와 별도 evaluator_source_sha256이 실제 사용한 코드를 식별한다.
`verification.json`은 Spring 빌드에 포함된 소스 해시와 정상 작업 폴더의 일치도 기록한다.
합성 server-contract의 소스 ID는 의도적으로 SYNTHETIC이라고 표시했다. 실제 기동한 평가 서버로 가장하지 않는다.

로그 상수와 기록 함수는 [TestLogPath](../../../tracks/conversation/log_types.py), [TestLogs](../../../tracks/conversation/test_logs.py)의 Enum/람다 쌍으로 관리한다.
각 시나리오의 정답·설명 예시는 모델 입력에 넣지 않는다. 원문에 있는 인용이더라도 주장이 지지되는지는 review.csv로 따로 판정한다.
실제 모델 관측이 없으므로 검수만 추가해 이 MOCK를 실제 품질 성공으로 바꿀 수 없다.

실제 평가 전에는 공유 소스의 평가 서버 두 개를 준비하고 계정·소스 해시·모델·GPU·별도 예산을 대조해야 한다.
지금 저장된 9개 결과는 그 서버들을 대신하는 응답 fixture의 연결 검증이다.

남은 구현·검증 범위는 [요구 사항별 기록](../../../../docs/evaluation/unified-conversation-implementation-20261104.md),
공통 실행법과 구조도는 [아키텍처](../../../../docs/architecture/unified-conversation-evaluation.md)에 정리했다.
