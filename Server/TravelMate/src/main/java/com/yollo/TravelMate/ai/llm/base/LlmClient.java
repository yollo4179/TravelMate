package com.yollo.TravelMate.ai.llm.base;

import java.util.List;

public interface LlmClient {
    String generate(String systemPrompt, String userPrompt);

    LlmTurn chat(List<LlmMessage> messages, List<LlmTurn.ToolDefinition> tools);

    /** Providers without native schema enforcement keep their plain chat path; the caller still validates the JSON. */
    default LlmTurn chat(List<LlmMessage> messages, List<LlmTurn.ToolDefinition> tools, StructuredOutput output) {
        return chat(messages, tools);
    }
}
