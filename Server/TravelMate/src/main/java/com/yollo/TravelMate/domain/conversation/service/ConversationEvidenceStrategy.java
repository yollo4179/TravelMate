package com.yollo.TravelMate.domain.conversation.service;

import java.util.UUID;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;

public interface ConversationEvidenceStrategy {
    boolean supports(ConversationToolRegistry registry);

    ConversationTool.Result prepare(
            String userUid,
            UUID turnKey,
            ConversationRequest request,
            ConversationToolRegistry registry
    );

    ConversationTool.Name source();
}
