package com.yollo.TravelMate.ai.llm.observation;

import java.time.Instant;
import java.util.UUID;
import java.util.function.Consumer;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.Builder;

public final class ObservationContext {
    private static final ThreadLocal<Context> CURRENT = new ThreadLocal<>();
    private static final ObjectMapper JSON = new ObjectMapper();
    private ObservationContext() {}

    public enum Mode { LIVE, MOCK, UNSCOPED }
    public enum Phase { REQUEST, CONVERSATION, PLAN_GENERATION, RECOMMENDATION_GENERATION }
    public enum Event {
        API_REQUEST, API_RESPONSE, EVIDENCE_PREPARATION, MODEL_CALL, MODEL_TURN, ROUTE, TOOL_ARGUMENT_ADAPTATION,
        TOOL_RESULT, TURN_RESULT, JOB_STATUS, EXCLUSION, PLAN_DRAFT, COVERAGE
    }

    @Builder(toBuilder = true)
    public record Context(
            String requestId,
            String turnId,
            String conversationId,
            String jobId,
            String parentToolCallId,
            Integer modelTurn,
            String caseId,
            String inputSha256,
            Mode mode,
            Phase phase,
            Consumer<JsonNode> sink
    ) {}

    public static Context capture() { return CURRENT.get(); }

    public static Scope open(Context context) {
        var previous = CURRENT.get();
        if (context == null) CURRENT.remove();
        else CURRENT.set(context);
        return () -> {
            if (previous == null) CURRENT.remove();
            else CURRENT.set(previous);
        };
    }

    public static Context child(Phase phase, String jobId, String toolCallId, Integer modelTurn) {
        Context current = capture();
        if (current == null) return null;
        return current.toBuilder().phase(phase).jobId(jobId)
                .parentToolCallId(toolCallId == null ? current.parentToolCallId() : toolCallId)
                .modelTurn(modelTurn).build();
    }

    public static void record(Event kind, JsonNode payload) {
        Context current = capture();
        if (current == null) return;
        ObjectNode event = JSON.createObjectNode();
        event.put("schemaVersion", 1).put("eventId", UUID.randomUUID().toString()).put("event", kind.name());
        event.put("timestamp", Instant.now().toString()).put("requestId", current.requestId()).put("turnId", current.turnId());
        event.put("conversationId", current.conversationId()).put("jobId", current.jobId());
        event.put("parentToolCallId", current.parentToolCallId()).put("modelTurn", current.modelTurn());
        event.put("caseId", current.caseId()).put("inputSha256", current.inputSha256());
        event.put("mode", current.mode().name()).put("phase", current.phase().name());
        event.set("payload", payload);
        current.sink().accept(event);
    }

    @FunctionalInterface
    public interface Scope extends AutoCloseable {
        @Override void close();
    }
}
