package com.yollo.TravelMate.domain.conversation.data;

import java.util.Arrays;
import java.util.List;

/** Optional UI intent hint; the same model judges the message and available evidence. */
public enum ConversationIntent {
        AUTO,          // No button selected: infer from the actual question.
        CONVERSATION,  // Dialogue, including travel questions without candidate selection.
        RECOMMENDATION,// Candidate places; even one candidate is returned as an array.
        PLAN;          // Draft itinerary request; queued jobs are not completed plans.

        private static final List<ConversationIntent> FINAL_VALUES = Arrays.stream(values())
                .filter(value -> value != AUTO)
                .toList();

        /** AUTO is only a request hint, so the Strict schema and the prompt share this answer-side subset. */
        public static List<ConversationIntent> finalValues() {
            return FINAL_VALUES;
        }
}
