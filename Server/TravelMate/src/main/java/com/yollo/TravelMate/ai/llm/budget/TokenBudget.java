package com.yollo.TravelMate.ai.llm.budget;

import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.ai.llm.base.LlmProvider;
import lombok.Builder;

public final class TokenBudget {
    private TokenBudget() {}
    public enum Quality { CONFIRMED_API, EXACT_LOCAL_CROSSCHECKED, CONSERVATIVE_BOUND, ESTIMATE }
    public enum Status { SUCCEEDED, FAILED, BUDGET_REJECTED, COUNT_UNAVAILABLE }

    @Builder
    public record Limits(
            LlmProvider provider,
            String model,
            long contextTokens,
            long outputReservation,
            long modelOutputLimit,
            String limitsModel,
            String limitsSource
    ) {}

    public record Count(
            long inputTokens,
            Quality quality,
            String method,
            Long nativeContextTokens,
            JsonNode evidence
    ) {}

    public record Usage(
            Long inputTokens,
            Long outputTokens,
            Long reasoningTokens,
            Long cachedInputTokens
    ) {
        public static Usage missing() { return new Usage(null, null, null, null); }
    }

    public record Receipt(Usage usage, JsonNode nativeToolCalls, String nativeStatus) {}

    public static Long reported(JsonNode response, String field) {
        JsonNode value = response.path(field);
        return value.isIntegralNumber() && value.canConvertToLong() && value.longValue() >= 0 ? value.longValue() : null;
    }
}
