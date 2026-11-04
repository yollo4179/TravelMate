package com.yollo.TravelMate.domain.conversation.service;

import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationRoutingModule;

/** One strategy per LiLi branch; LiliRouterV1 selects exactly one by supports(). */
public interface LiliBranchHandler {
    record Input(
            ConversationRoutingModule.Turn turn,
            LiliTurns.Decision decision
    ) {}

    boolean supports(LiliBranch branch);

    ConversationResponse execute(Input input);
}
