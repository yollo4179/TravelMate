package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.List;
import com.yollo.TravelMate.ai.llm.base.LlmMessage;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.base.StructuredOutput;

public interface ModelModule {
    enum Version { GUARDED_V1 }

    /** output is null for the single-LLM path, whose answer schema the provider derives from the offered tools. */
    record Input(
            List<LlmMessage> messages,
            List<LlmTurn.ToolDefinition> tools,
            StructuredOutput output
    ) {
        public Input {
            messages = List.copyOf(messages);
            tools = List.copyOf(tools);
        }

        public Input(List<LlmMessage> messages, List<LlmTurn.ToolDefinition> tools) {
            this(messages, tools, null);
        }
    }

    boolean supports(Version version);

    LlmTurn execute(Input input, ConversationModuleConfig config);
}
