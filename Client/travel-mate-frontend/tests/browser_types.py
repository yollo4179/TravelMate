"""Browser-only scenarios; none are live model verdicts."""
from enum import StrEnum


class BrowserScenario(StrEnum):
        # 대화와 추천: 응답 문장·근거·캐릭터 표정 표시.
        CONVERSATION = "conversation"
        RECOMMENDATION = "recommendation"
        # 계획: 접수와 완성된 초안 배열을 구분.
        PLAN_ACCEPTED = "plan_accepted"
        PLAN_READY = "plan_ready"
