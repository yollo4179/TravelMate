package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.List;
import com.yollo.TravelMate.ai.llm.base.LlmMessage;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;

public interface ModelModule {
    enum Version { GUARDED_V1 }

    record Input(List<LlmMessage> messages, List<LlmTurn.ToolDefinition> tools) {
        public Input {
            messages = List.copyOf(messages);
            tools = List.copyOf(tools);
        }
    }

    boolean supports(Version version);

    LlmTurn execute(Input input, ConversationModuleConfig config);
}
