package com.yollo.TravelMate.domain.conversation.data;

import java.util.List;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.Builder;

@Builder
public record ConversationResponse(
        ResultType type,
        JsonNode data,
        String message,
        List<Citation> citations,
        Termination termination,
        int modelTurns,
        List<ToolObservation> toolResults
) {
    public enum ResultType { TEXT, PLACES, PLANNING_JOB, DRAFT, ERROR }
    public enum Termination { COMPLETED, MODEL_FAILED, INVALID_RESPONSE, MODEL_LIMIT, TOOL_LIMIT }
    public enum ToolStatus { SUCCEEDED, FAILED, CACHED }

    public record Citation(Long placeId, String evidenceId, String sourceId, String quote) {}

    public record ToolObservation(
            String callId,
            String name,
            String arguments,
            ToolStatus status,
            ResultType type,
            JsonNode publicData
    ) {}
}
