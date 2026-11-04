package com.yollo.TravelMate.domain.conversation.pipeline;

import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;

public interface PromptModule {
    enum Version { RESOURCE_V1 }

    boolean supports(Version version);

    String execute(ConversationRequest input, ConversationModuleConfig config);

    String sha256();
}
