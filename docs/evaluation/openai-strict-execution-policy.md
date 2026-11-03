# OpenAI strict 2문항 실행 정책

이번 작업의 완료 범위는 기존 `PLR-TM-palaces-01`, `PLR-TM-palaces-03`의 검색 도구 연결 검증이다. [완료 보고서](../../Evaluation/runs/contextual/openai-strict-search-two-case-v1/20261103-01/REPORT.md)에 실행 당시 정책·사용량·결과를 보존했다.

`OpenAiBatchBudget.Policy.inputCountCostPolicy`의 기본값은 `REQUIRE_CONFIRMED`다. 계산 API의 과금 근거와 상한이 확인되지 않았고 명시적인 예외 허용도 없다면 HTTP 전달 전에 차단한다.

사용자가 허용한 이번 실행에는 `ALLOW_UNVERIFIED`를 명시했다. 이 모드에서는 계산 비용을 확인됐다고 표시하거나 0원으로 설정할 수 없다. `inputCountBillingConfirmed=false`, 과금 근거와 금액은 null이어야 한다. 추론비 상한과 미확인 계산 비용을 분리하고 총 청구액 `$0.10`을 보장하지 않는다.

실행 설정은 모델 `gpt-5.4-mini-2026-03-17`, 추론비 상한 `$0.047616`, 추론·계산 각 최대 4회, 문항별 모델 턴 최대 2회, 검색 최대 2회다. 재시도·계획·judge·추가 문항을 허용하지 않는다. 실패한 요청도 예약을 소비하며 기존 원장을 덮어써서 재시작할 수 없다. 미확인 비용과 청구서 확정 여부는 최종 기록에서도 각각 null·false로 남긴다.

보존된 `approved-inference-policy.json`의 approved는 **완료된 해당 실행의 과거 승인 기록**이며 새로운 실행 허가나 기본 설정이 아니다. 실제 서버의 민감 설정 파일·키·JWT 비밀값·JAR는 PR에 포함하지 않는다. 검사 결과는 보존한 [패키징 검사 XML](../../Evaluation/runs/contextual/openai-strict-search-two-case-v1/20261103-01/checks/packaged-junit/TEST-com.yollo.TravelMate.OpenAiBatchBudgetTest.xml)의 16개를 연결하며 이번 정리 작업에서 재실행하지 않는다.
