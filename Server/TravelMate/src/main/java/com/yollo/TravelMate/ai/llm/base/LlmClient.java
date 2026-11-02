package com.yollo.TravelMate.ai.llm.base;

import java.util.List;

public interface LlmClient {
    String generate(String systemPrompt, String userPrompt);

    LlmTurn chat(List<LlmMessage> messages, List<LlmTurn.ToolDefinition> tools);
}
