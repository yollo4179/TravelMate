package com.yollo.TravelMate.ai.llm.base;

import org.springframework.web.client.RestClient;

public interface LlmClient {
	
	/**
     * 프롬프트를 주고 텍스트 응답을 받는다.
     * (thinking off, non-stream, JSON 생성용으로 temperature 낮게 고정)
     */
	
	String generate(String systemPrompt, String userPrompt);
	
	
	
	
}
