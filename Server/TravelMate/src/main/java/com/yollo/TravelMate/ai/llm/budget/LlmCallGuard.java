package com.yollo.TravelMate.ai.llm.budget;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.UUID;
import java.util.function.Function;
import java.util.function.Supplier;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.observation.*;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import static com.yollo.TravelMate.ai.llm.budget.TokenBudgetException.Reason;

@Component
@RequiredArgsConstructor
public class LlmCallGuard {
    private final ObjectMapper mapper;
    private final ExecutionRecorder recorder;

    public LlmTurn call(
            TokenBudget.Limits limits,
            JsonNode wireRequest,
            Supplier<TokenBudget.Count> counter,
            Supplier<JsonNode> inference,
            Function<JsonNode, TokenBudget.Receipt> receipt,
            Function<JsonNode, LlmTurn> decoder
    ) {
        try (var scope = recorder.ensureScope()) {
            long started = System.nanoTime();
            long countStarted = started;
            Double countDuration = null;
            Double inferenceDuration = null;
            TokenBudget.Count count = null;
            TokenBudget.Receipt observed = new TokenBudget.Receipt(TokenBudget.Usage.missing(), null, null);
            TokenBudget.Status status = TokenBudget.Status.FAILED;
            String failure = null;
            boolean dispatched = false;
            var event = mapper.createObjectNode().put("callId", UUID.randomUUID().toString())
                    .put("startedAt", Instant.now().toString()).put("provider", limits.provider().name())
                    .put("model", limits.model()).put("wireSha256", sha256(wireRequest.toString()))
                    .put("wireUtf8Bytes", wireRequest.toString().getBytes(StandardCharsets.UTF_8).length);
            event.set("limits", mapper.valueToTree(limits));
            event.set("coverage", mapper.valueToTree(java.util.List.of(
                    "complete_native_system_and_messages", "conversation_history", "tool_definitions",
                    "full_original_evidence_and_conditions_in_tool_messages", "all_accumulated_tool_results",
                    "native_reasoning_continuation", "reserved_output_including_hidden_tokens"
            )));
            try {
                validateLimits(limits);
                countStarted = System.nanoTime();
                try { count = counter.get(); }
                catch (RuntimeException exception) { throw new TokenBudgetException(Reason.COUNT_UNAVAILABLE); }
                finally { countDuration = elapsed(countStarted); }
                validateCount(limits, count);
                event.set("count", mapper.valueToTree(count));
                // 관측 저장이 실패하면 추론을 시작하지 않는다.
                ObservationContext.record(ObservationContext.Event.MODEL_CALL, event.deepCopy().put("stage", "PREFLIGHT_ACCEPTED"));
                long inferenceStarted = System.nanoTime();
                dispatched = true;
                final JsonNode response;
                try { response = inference.get(); }
                finally { inferenceDuration = elapsed(inferenceStarted); }
                if (response != null) observed = receipt.apply(response);
                var decoded = decoder.apply(response);
                status = TokenBudget.Status.SUCCEEDED;
                return decoded;
            } catch (TokenBudgetException exception) {
                status = exception.reason() == Reason.COUNT_UNAVAILABLE
                        ? TokenBudget.Status.COUNT_UNAVAILABLE : TokenBudget.Status.BUDGET_REJECTED;
                failure = exception.reason().name();
                throw exception;
            } catch (RuntimeException exception) {
                failure = exception.getClass().getSimpleName();
                throw exception;
            } finally {
                event.put("stage", "FINISHED").put("status", status.name()).put("failure", failure)
                        .put("dispatched", dispatched).put("durationMs", elapsed(started));
                event.put("countDurationMs", countDuration).put("inferenceDurationMs", inferenceDuration);
                event.set("count", mapper.valueToTree(count));
                event.set("receipt", mapper.valueToTree(observed));
                ObservationContext.record(ObservationContext.Event.MODEL_CALL, event);
            }
        }
    }

    private static void validateLimits(TokenBudget.Limits limits) {
        if (limits.model() == null || limits.model().isBlank() || limits.contextTokens() < 1
                || limits.modelOutputLimit() < 1 || !limits.model().equals(limits.limitsModel())
                || limits.limitsSource() == null || limits.limitsSource().isBlank()) {
            throw new TokenBudgetException(Reason.LIMITS_UNVERIFIED);
        }
        if (limits.outputReservation() < 1 || limits.outputReservation() > limits.modelOutputLimit()) {
            throw new TokenBudgetException(Reason.OUTPUT_LIMIT);
        }
    }

    private static void validateCount(TokenBudget.Limits limits, TokenBudget.Count count) {
        if (count == null || count.inputTokens() < 0
                || (count.quality() != TokenBudget.Quality.CONFIRMED_API
                    && count.quality() != TokenBudget.Quality.CONSERVATIVE_BOUND)
                || (count.nativeContextTokens() != null && count.nativeContextTokens() < 1)) {
            throw new TokenBudgetException(Reason.COUNT_UNVERIFIED);
        }
        long context = count.nativeContextTokens() == null ? limits.contextTokens()
                : Math.min(limits.contextTokens(), count.nativeContextTokens());
        if (limits.outputReservation() > context || count.inputTokens() > context - limits.outputReservation()) {
            throw new TokenBudgetException(Reason.CONTEXT_LIMIT);
        }
    }

    public static String sha256(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException exception) { throw new IllegalStateException(exception); }
    }

    private static double elapsed(long started) { return (System.nanoTime() - started) / 1_000_000.0; }
}
