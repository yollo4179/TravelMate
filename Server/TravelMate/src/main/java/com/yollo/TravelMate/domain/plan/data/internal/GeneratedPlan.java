package com.yollo.TravelMate.domain.plan.data.internal;

import java.util.List;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;

/** dialogue is LiLi's 2-4 cuts presenting the draft; null only for drafts written without a model call. */
public record GeneratedPlan(
        String planTitle,
        String planDescription,
        List<GeneratedPin> pins,
        List<DialogueCut> dialogue
) {
    public GeneratedPlan(String planTitle, String planDescription, List<GeneratedPin> pins) {
        this(planTitle, planDescription, pins, null);
    }

    public record GeneratedPin(
            Long placeId,
            Integer sequence,
            String activity,
            String reason,
            List<SourceCitation> citations
    ) {
        public GeneratedPin {
            citations = citations == null ? List.of() : List.copyOf(citations);
        }

        public GeneratedPin(
                Long placeId,
                Integer sequence,
                String activity,
                String reason
        ) {
            this(placeId, sequence, activity, reason, List.of());
        }
    }

    public record SourceCitation(String evidenceId, String sourceId, String quote) {}
}
