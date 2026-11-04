package com.yollo.TravelMate.domain.conversation.data;

import java.util.List;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.Builder;

@Builder(toBuilder = true)
public record ConversationResponse(
        ResultType type,
        JsonNode data,
        String message,
        List<Citation> citations,
        Termination termination,
        int modelTurns,
        List<ToolObservation> toolResults,
        String requestId,
        String turnId,
        String conversationId,
        String primaryResultId,
        MessageSource messageSource,
        ConversationIntent intent,
        CharacterEmotion emotion,
        List<JsonNode> items,
        List<DialogueCut> dialogue,
        List<String> choices
) {
    public ConversationResponse {
        emotion = emotion == null ? CharacterEmotion.NEUTRAL : emotion;
        intent = intent == null ? ConversationIntent.CONVERSATION : intent;
        // message/emotion stay the first cut so clients that read one line keep working.
        if (dialogue == null || dialogue.isEmpty()) {
            dialogue = message == null || message.isBlank() ? List.of() : List.of(new DialogueCut(message, emotion));
        }
        dialogue = List.copyOf(dialogue);
        choices = choices == null ? List.of() : List.copyOf(choices);
        // Preserve authoritative legacy data, while all candidate/plan consumers use arrays.
        if (items == null) {
            items = data == null || data.isNull() ? List.of()
                    : data.isArray() ? java.util.stream.StreamSupport.stream(data.spliterator(), false).toList()
                    : type == ResultType.DRAFT ? List.of(data) : List.of();
        }
        items = List.copyOf(items);
    }

    public enum ResultType { TEXT, PLACES, PLANNING_JOB, RECOMMENDATION_JOB, DRAFT, ERROR }
    public enum Termination { COMPLETED, MODEL_FAILED, INVALID_RESPONSE, MODEL_LIMIT, TOOL_LIMIT, TOOL_FAILED, BUDGET_REJECTED, COUNT_UNAVAILABLE }
    public enum ToolStatus { SUCCEEDED, FAILED, CACHED }
    public enum MessageSource { LLM, SERVER_RECEIPT, SERVER_FALLBACK }

    public record Citation(Long placeId, String evidenceId, String sourceId, String quote) {}

    public record ToolObservation(
            String callId,
            String name,
            String arguments,
            ToolStatus status,
            ResultType type,
            JsonNode publicData,
            String resultId
    ) {}
}
