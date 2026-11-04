package com.yollo.TravelMate.ai.llm.base;

import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;

@Primary
@Component
public class StrategyLlmClient implements LlmClient {
    private final LlmStrategy selected;

    public StrategyLlmClient(
            List<LlmStrategy> strategies,
            @Value("${llm.provider:OPENAI}") LlmProvider provider
    ) {
        var matches = strategies.stream().filter(strategy -> strategy.supports(provider)).toList();
        if (matches.size() != 1) {
            throw new IllegalStateException("LLM 공급자에 맞는 전략은 정확히 하나여야 합니다: " + provider);
        }
        selected = matches.get(0);
    }

    @Override
    public String generate(String systemPrompt, String userPrompt) {
        return selected.generate(systemPrompt, userPrompt);
    }

    @Override
    public LlmTurn chat(List<LlmMessage> messages, List<LlmTurn.ToolDefinition> tools) {
        return selected.chat(messages, tools);
    }
}
