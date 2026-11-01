package com.yollo.TravelMate;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.observation.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class TokenBudgetGuardTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @ParameterizedTest
    @CsvSource({"80,100,20,CONFIRMED_API,true", "81,100,20,CONFIRMED_API,false",
            "80,90,20,CONFIRMED_API,false", "80,100,20,CONSERVATIVE_BOUND,true",
            "80,100,20,EXACT_LOCAL_CROSSCHECKED,true", "81,100,20,EXACT_LOCAL_CROSSCHECKED,false",
            "10,100,20,ESTIMATE,false", "10,100,51,CONFIRMED_API,false",
            "10,0,20,CONFIRMED_API,false", "10,100,20,,false"})
    void rejectsBeforeDispatchAndDistinguishesExactCountsBoundsAndEstimates(
            long inputTokens,
            long nativeContext,
            long reservation,
            TokenBudget.Quality quality,
            boolean accepted
    ) {
        List<JsonNode> events = new ArrayList<>();
        var guard = new LlmCallGuard(mapper, mock(ExecutionRecorder.class));
        var limits = TokenBudget.Limits.builder().provider(LlmProvider.OPENAI).model("model-mock")
                .contextTokens(100).outputReservation(reservation).modelOutputLimit(50)
                .limitsModel("model-mock").limitsSource("MOCK limits").build();
        AtomicInteger dispatches = new AtomicInteger();
        try (var scope = ObservationContext.open(context(events))) {
            var count = new TokenBudget.Count(inputTokens, quality, "MOCK_COUNTER", nativeContext, mapper.nullNode());
            var operation = (java.util.function.Supplier<LlmTurn>) () -> guard.call(
                    limits,
                    mapper.createObjectNode().put("input", "원문을 자르지 않는다. 통행할 수 없었다."),
                    () -> count,
                    () -> { dispatches.incrementAndGet(); return mapper.createObjectNode(); },
                    response -> new TokenBudget.Receipt(TokenBudget.Usage.missing(), null, null),
                    response -> LlmTurn.builder().content("response").build()
            );
            if (accepted) assertEquals("response", operation.get().content());
            else assertThrows(TokenBudgetException.class, operation::get);
        }
        assertEquals(accepted ? 1 : 0, dispatches.get());
        JsonNode finished = events.get(events.size() - 1).get("payload");
        assertEquals(accepted, finished.get("dispatched").booleanValue());
        assertEquals(accepted ? "SUCCEEDED" : "BUDGET_REJECTED", finished.get("status").textValue());
        assertTrue(finished.path("receipt").path("usage").path("inputTokens").isNull(), "미관측 사용량을 0으로 만들지 않는다");
        assertEquals("MOCK", events.get(0).path("mode").asText());
    }

    @Test
    void unavailableCounterBlocksTheProviderAndRecordsASeparateFailure() {
        List<JsonNode> events = new ArrayList<>();
        var guard = new LlmCallGuard(mapper, mock(ExecutionRecorder.class));
        var limits = TokenBudget.Limits.builder().provider(LlmProvider.OPENAI).model("model-mock")
                .contextTokens(100).outputReservation(20).modelOutputLimit(50)
                .limitsModel("model-mock").limitsSource("MOCK limits").build();
        AtomicInteger dispatches = new AtomicInteger();
        try (var scope = ObservationContext.open(context(events))) {
            var failure = assertThrows(TokenBudgetException.class, () -> guard.call(
                    limits,
                    mapper.createObjectNode(),
                    () -> { throw new IllegalStateException("counter unavailable"); },
                    () -> { dispatches.incrementAndGet(); return mapper.createObjectNode(); },
                    response -> new TokenBudget.Receipt(TokenBudget.Usage.missing(), null, null),
                    response -> LlmTurn.builder().build()
            ));
            assertEquals(TokenBudgetException.Reason.COUNT_UNAVAILABLE, failure.reason());
        }
        assertEquals(0, dispatches.get());
        assertEquals("COUNT_UNAVAILABLE", events.get(0).path("payload").path("status").asText());
    }

    static ObservationContext.Context context(List<JsonNode> events) {
        return ObservationContext.Context.builder().requestId("request-mock").turnId("turn-mock")
                .conversationId("conversation-mock").mode(ObservationContext.Mode.MOCK)
                .phase(ObservationContext.Phase.CONVERSATION).sink(event -> events.add(event.deepCopy())).build();
    }
}
