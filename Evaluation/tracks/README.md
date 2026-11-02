# 트랙 실행과 구현 상태

검색 전용 수집·runtime 대조는 [독립 검색 평가 계약](search/README.md)으로 연결한다.
직접 HTTP 기록과 native LLM 도구 기록의 원본/변환/관측 범위를 구분한다.
과거 단계별 구현 목록보다 이 계약과 실제 코드가 현재 검색 도구의 기준이다.

모든 run.py는 check / export-inputs / evaluate를 제공한다.
evaluate는 저장된 응답을 채점하며 앱 API·도구·DB를 실행하지 않는다.
--split development/test/all을 반드시 지정하며 --type으로 기대 응답 타입을 좁힐 수 있다.

| 트랙 | 현재 대상 | 코드 검사 / GPT |
|---|---|---|
| search | 기존 검색 문항 85개 | 임베딩·리랭킹 순위에 동일 Top-1/5/10 및 여섯 순위 지표, judged@K |
| tool_call | 200개 | 도구 이름·스키마·고정 인자, 호출 P/R/F1. query 의미는 선택적 GPT |
| plan | 50개 | 선택 ID·조건·가상 시간·경로 비용. 설명은 선택적 GPT |
| state | 70개 | 미리보기·확정·관측 버전·비계획 데이터 보존 |
| memory | 20개 | 시나리오 기억 ID 순위, 일부 명시/추론 취향 관측. 최종 발화는 선택적 GPT |
| behavior | 45개 | 타입·기대 도구·상태와 선택적 GPT의 의도/금지 주장 검사 |
| persona | 기존 message 200개의 별칭 | 코드 형식 검사와 선택적 GPT의 기존 페르소나 기준 |
| message | 200개 | 코드 형식/도구 검사와 기존 네 가지 GPT 발화 기준 |
| end_to_end | 200개 | 저장된 전체 기록의 기존 채점기 조합. 실제 E2E 실행기는 아님 |

트랙은 문항과 출력 지표를 선택한다. 타입은 PLACES/PLAN/PLAN_DIFF/CLARIFICATION/TEXT의
클라이언트 응답 형식이다. 둘은 1:1 관계가 아니다. 특정 트랙에서도 GPT를 켜면 기존 네 가지
발화 기준을 적용하고, 적용 불가는 null로 남긴다. 새 가중치나 종합 점수를 만들지 않았다.

## 실제 구현된 파일

- search/score_ranking.py → common/metrics/ranking.py: 임베딩 전용과 리랭킹 후 순서를 동일 기준으로 계산
- search/collect_live.py, collect_holdout.py: 명시적 case·한도·대상의 독립 HTTP 검색 수집. 원본과 평가용 변환 분리
- search/inspect_holdout_runtime.py: 저장 corpus/원문/청크/관계·설정·실제 장치 대조. MOCK는 LIVE 확인이 아님
- search/judge_candidates.py, audit_candidate_conditions.py: 명시적 모델·출력·호출 상한의 후보 근거 판정. 자동 유료 재시도 없음
- search/compare_holdout.py: 저장 라벨·블라인드 매핑·원본 관측의 잠정 비교. unknown/미관측 제외
- search/summarize_langsmith.py, publish_metrics.py: 저장 span 집계 및 별도 설정에 따른 bounded 조회/게시
- tool_call/score_args.py: 도구 호출 정규화·이름/인자/스키마 비교
- plan/score_rules.py, score_route.py: 후보·조건·제공 비용 행렬의 경로/시간
- state/score.py: 실제 backend_observation 확인
- memory/score_extraction.py, score_retrieval.py: 기존 추출/확인 및 기억별 순위 검사
- end_to_end/score.py: 기존 코드 검사 조합
- common/judge/: 기존 GPT 메시지 평가, JSON 출력·근거 인용 검사

## 아직 없는 기능

전체 Agent의 여러 턴 평가 재생·DB 기억 추출 실행·실제 도로 비용 연동·V1.4 Ragas ID 전용 실행기는 미구현이다.
기존 native 단일 LLM 도구·비동기 Job/DRAFT 관측은 연결돼 있지만 DRAFT를 PLAN 평가 계약으로 바꾸지 않는다.
계획의 실제 조건 준수·수정/확정/롤백·실제 이동시간/최적화 품질을 이번 검색 도구 정리로 완료 처리하지 않는다.
검색/후보 judge/수동 게시 도구는 구현했으나 실제 모델·검색·게시 검증은 별도 승인 범위다.
