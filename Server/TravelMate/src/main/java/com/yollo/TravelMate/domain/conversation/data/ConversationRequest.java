package com.yollo.TravelMate.domain.conversation.data;

import java.util.List;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import jakarta.validation.Valid;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchContext;
import jakarta.validation.constraints.*;

public record ConversationRequest(
        @NotBlank @Size(max = 4000) String message,
        @Valid GeneratePlanRequest planningRequest,
        @Size(max = 20) List<@NotNull @Valid HistoryMessage> history,
        @Valid PlaceSearchContext searchContext,
        ConversationIntent intentHint
) {
    public ConversationRequest {
        intentHint = intentHint == null ? ConversationIntent.AUTO : intentHint;
        history = history == null ? List.of() : List.copyOf(history);
    }

    public ConversationRequest(String message, GeneratePlanRequest planningRequest, List<HistoryMessage> history) {
        this(message, planningRequest, history, null);
    }

    public ConversationRequest(String message, GeneratePlanRequest planningRequest, List<HistoryMessage> history, PlaceSearchContext searchContext) {
        this(message, planningRequest, history, searchContext, ConversationIntent.AUTO);
    }

    /** LiLi's search query replaces the raw sentence for retrieval; the original turn stays in the job payload. */
    public ConversationRequest withMessage(String replacement) {
        return new ConversationRequest(replacement, planningRequest, history, searchContext, intentHint);
    }

    public ConversationRequest withPlanningRequest(GeneratePlanRequest replacement) {
        return new ConversationRequest(message, replacement, history, searchContext, intentHint);
    }

    public enum HistoryRole { USER, ASSISTANT }

    public record HistoryMessage(
            @NotNull HistoryRole role,
            @NotBlank @Size(max = 8000) String content
    ) {}
}
