package com.yollo.TravelMate.domain.conversation.data;

import java.util.List;
import java.util.stream.Stream;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import jakarta.validation.Valid;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchContext;
import jakarta.validation.constraints.*;

public record ConversationRequest(
        @NotBlank @Size(max = 4000) String message,
        @Valid GeneratePlanRequest planningRequest,
        @Size(max = 20) List<@NotNull @Valid HistoryMessage> history,
        @Valid PlaceSearchContext searchContext,
        ConversationIntent intentHint,
        @Valid DisplayedResult displayedResult
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

    public ConversationRequest(
            String message,
            GeneratePlanRequest planningRequest,
            List<HistoryMessage> history,
            PlaceSearchContext searchContext,
            ConversationIntent intentHint
    ) {
        this(message, planningRequest, history, searchContext, intentHint, null);
    }

    /** LiLi's search query replaces the raw sentence for retrieval; the original turn stays in the job payload. */
    public ConversationRequest withMessage(String replacement) {
        return new ConversationRequest(replacement, planningRequest, history, searchContext, intentHint, displayedResult);
    }

    public ConversationRequest withPlanningRequest(GeneratePlanRequest replacement) {
        return new ConversationRequest(message, replacement, history, searchContext, intentHint, displayedResult);
    }

    /** Adds the places the user excluded to the app's existing exclusions; region and other filters stay as sent. */
    public ConversationRequest withExcludedPlaces(List<Long> placeIds) {
        if (placeIds.isEmpty()) return this;
        var base = searchContext == null ? new PlaceSearchContext(null, null, null, List.of(), null) : searchContext;
        var merged = Stream.concat(base.excludePlaceIds().stream(), placeIds.stream()).distinct().toList();
        var context = new PlaceSearchContext(base.region(), base.city(), base.category(), merged, base.area(), base.themes());
        return new ConversationRequest(message, planningRequest, history, context, intentHint, displayedResult);
    }

    public enum HistoryRole { USER, ASSISTANT }

    public record HistoryMessage(
            @NotNull HistoryRole role,
            @NotBlank @Size(max = 8000) String content
    ) {}
}
