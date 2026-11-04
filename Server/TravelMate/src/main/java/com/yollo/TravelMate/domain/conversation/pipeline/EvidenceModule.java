package com.yollo.TravelMate.domain.conversation.pipeline;

import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;

public interface EvidenceModule {
    enum Version { ORIGINAL_V1 }

    boolean supports(Version version);

    ConversationTool.Result execute(SearchModule.Batch input, ConversationModuleConfig config);
}
