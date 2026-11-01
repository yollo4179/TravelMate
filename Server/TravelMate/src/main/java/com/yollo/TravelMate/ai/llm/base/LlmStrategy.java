package com.yollo.TravelMate.ai.llm.base;

public interface LlmStrategy extends LlmClient {
    boolean supports(LlmProvider provider);
}
