# 백업 정리 기록과 구현 버전 관리

이 문서는 기존 로컬 정리 영수증을 Git에 기록한다. 이번 커밋에서는 추가 백업 삭제를 수행하지 않는다. 현재 작업 공간에 보존된 코드·평가 데이터·문서·이미지도 함께 버전 관리한다.

## 완료된 정리

| 대상 | 정리 결과 | 보존 근거 |
|---|---|---|
| 최초 작업 백업 | 원본 83개 유지, 백업 중 중복 10개 삭제, 73개 유지 | 현재 원본과 `4ced99c57276669d9d581d611b1d79815e961581`의 동일 경로 Git blob에 대해 바이트 해시가 일치하는 사본만 삭제 |
| OpenAI strict 실행 사본 4개 | 실행 폴더와 임시 압축 전 사본 제거, 순 확보 555,216,112바이트 | Git 보존 파일, 로컬 ZIP 보존 파일, 재생성 가능한 산출물로 분류 |
| `evaluation-tool-contracts-lf` 작업 트리 | Git과 동일한 파일 1,235개 정리, 바이트 변형 1개와 미수록 파일 74개 별도 유지 | 대응 커밋 `27df85d79fe248275e6fd4fe9d4c9cf65559928a`, 원본·미반영 백업 해시 보존 확인 |

원본 영수증은 [initial-cleanup-receipt.json](initial-cleanup-receipt.json), [runtime-retirement-receipt.json](runtime-retirement-receipt.json), [worktree-cleanup-receipt.json](worktree-cleanup-receipt.json)에 보존한다. 영수증의 경로와 상태는 정리 당시의 기록이며, 이후 Git 반영 상태를 뜻하지 않는다.

## 로컬 보존 자료

- `.local-backups/branch-cleanup-20261102-1922/files/`: 미반영·보호·판정 불명확 백업 73개.
- `.local-backups/backup-cleanup-pr8/`: 최초 삭제 목록·보존 목록·보호 목록 및 파일별 해시.
- `.local-backups/backup-cleanup-pr8/runtime-retirement/plan.json`: 실행 사본별 Git·ZIP·재생성 산출물 대응 기록.
- `.local-backups/backup-cleanup-conversation-20261103-01/`: 작업 트리 파일별 복원 계획과 보존한 변형·미수록 파일.
- `.local-backups/openai-strict-local-only.zip`: Git 미수록 고유 파일 106개, 5,308,846바이트. SHA-256: `b07b82fd76b149b4b598a54d44f55bbbeef3609cb89f7f41b67eb1a76450f948`.

ZIP에는 로컬 인증 설정이 포함될 수 있으므로 로컬에 유지한다. `.local-backups/` 전체를 `.gitignore`에서 제외한다. 기존 평가 원본·다른 작업 트리·DB·공유 모델 캐시는 위 영수증의 정리 범위에서 보존했다.

## 앞으로의 구현 관리

실제로 비교·운영할 동작은 공통 `execute()` 인터페이스의 구현 클래스로 분리한다. 설정 차이는 동일 구현체에 전달하고, 단순 수정 이력은 Git에 남긴다. 프로젝트·런타임 전체를 버전마다 복제하지 않는다.

구현체 선택, 공통 호출 제한·원장 적용, 평가 원본 보존 규칙은 루트 [AGENTS.md](../../../AGENTS.md)의 구현 버전 관리 및 공통 실행 규칙에 명시한다. 이번 변경은 기존 구현 전체를 재설계한 것이 아니라 이후 작업이 따라야 할 규칙을 추가한 것이다.
