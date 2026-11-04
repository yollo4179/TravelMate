package com.yollo.TravelMate.domain.conversation.data;

/** Optional UI intent hint; the same model judges the message and available evidence. */
public enum ConversationIntent {
        AUTO,          // No button selected: infer from the actual question.
        CONVERSATION,  // Dialogue, including travel questions without candidate selection.
        RECOMMENDATION,// Candidate places; even one candidate is returned as an array.
        PLAN           // Draft itinerary request; queued jobs are not completed plans.
}
