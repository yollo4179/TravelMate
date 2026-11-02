package com.yollo.TravelMate.domain.plan.data.internal;

import java.util.List;

public record GeneratedPlan(
        String planTitle,
        String planDescription,
        List<GeneratedPin> pins
) {
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
