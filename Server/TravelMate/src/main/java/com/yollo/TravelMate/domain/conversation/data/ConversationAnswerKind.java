package com.yollo.TravelMate.domain.conversation.data;

/** Final answer kind shared by the Strict schema, the prompt vocabulary and the renderer. */
public enum ConversationAnswerKind {
        PLACE_GUIDANCE,  // Grounded place explanation; verified place data stays in items.
        CONVERSATION,    // Dialogue without candidate selection.
        CLARIFICATION    // Asks for missing conditions instead of guessing.
}
