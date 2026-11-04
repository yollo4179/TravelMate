package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.UUID;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;

/** How one conversation turn is handled; versions stay side by side so they can be compared on the same cases. */
public interface ConversationRoutingModule {
    enum Version {
        SINGLE_LLM_V1,   // Pre-retrieve places for every message and let one model answer or call any tool.
        LILI_ROUTER_V1   // LiLi replies first without evidence and picks a branch; search and plans run as jobs.
    }

    record Turn(
            String userUid,
            UUID turnKey,
            ConversationRequest request
    ) {}

    boolean supports(Version version);

    ConversationResponse execute(Turn turn);
}
