package com.yollo.TravelMate.ai.llm.budget;

public class TokenBudgetException extends IllegalStateException {
    public enum Reason { LIMITS_UNVERIFIED, COUNT_UNAVAILABLE, COUNT_UNVERIFIED, OUTPUT_LIMIT, CONTEXT_LIMIT }
    private final Reason reason;

    public TokenBudgetException(Reason reason) {
        super("LLM 호출 전 토큰 예산 검사 실패: " + reason.name());
        this.reason = reason;
    }

    public Reason reason() { return reason; }
}
