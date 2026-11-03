# 보존 자료 안내

완료 범위와 확인 수준은 [REPORT.md](REPORT.md)에 명시했다. 이 폴더는 실행 당시의 원본·소스·설정·검사 기록을 보관하며 새 실행을 위한 환경이 아니다. 실행·검사·유료 호출·배포를 자동으로 시작하는 구성을 추가하지 않았다.

| 경로 | 내용 |
|---|---|
| `run.json`, `observations-summary.json` | 최종 실행 상태, 두 문항의 인자·결과·설명·인용·사용량·비용 |
| `raw/` | 실제 요청·응답·관측·시간·검색 추적·원문 해시 보존 확인 |
| `policy/` | 해당 실행의 과거 승인 정책, 실행 설정, 원장, 기대 스키마 |
| `transport/` | 실제 실행한 중계기 원본, chunked 본문·required 비교 변경 기록, 오프라인 검사 소스 |
| `checks/` | 기존 통과 XML, 전송 검사 4개 요청과 required 검사 12개, 배포·프로세스 확인 |
| `prior-runs/01`, `prior-runs/03` | 제공자 호출 이전의 실행 환경 실패. 모델 품질 집계에서 제외 |
| `prior-runs/02` | 수정 전 실제 category 선택 오류와 해당 배치 사용량·결과 |
| `artifact-provenance.json` | 로컬 보존 원본과 바이트 그대로 복사한 파일의 대응·SHA-256 |
| `version-correspondence.json` | 구현·중계기 버전, JAR·설정·스키마·결과 해시의 대응 |

`transport/run-once.py`, `transport/offline/verify_required_comparison.py`, 과거 보고서의 로컬 경로는 실행 당시 기록을 바이트 그대로 보존한 것이다. 이 저장 폴더에 맞춰 경로를 고치거나 실행 옵션을 추가하지 않았다. 재실행 안내나 새 승인을 의미하지 않는다. 기록된 사용자 승인·상한은 과거 배치에만 적용된다.

민감한 `spring.properties`, `private.json`, API 키·JWT 비밀값, 환경 파일, 실행 JAR·의존성·일반 서버 로그는 포함하지 않았다. 원본 runtime과 다른 미커밋 작업은 로컬에서 계속 보존한다.
