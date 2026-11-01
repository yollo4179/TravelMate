package com.yollo.TravelMate.domain.conversation.data;

import java.util.List;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;

public record ConversationRequest(
        @NotBlank @Size(max = 4000) String message,
        @Valid GeneratePlanRequest planningRequest,
        @Size(max = 20) List<@NotNull @Valid HistoryMessage> history
) {
    public ConversationRequest {
        history = history == null ? List.of() : List.copyOf(history);
    }

    public enum HistoryRole { USER, ASSISTANT }

    public record HistoryMessage(
            @NotNull HistoryRole role,
            @NotBlank @Size(max = 8000) String content
    ) {}
}
