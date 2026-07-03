package com.yollo.TravelMate.ai.llm.derived;

import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import com.yollo.TravelMate.ai.llm.base.LlmClient;

@Component
public class OllamaLlmClient implements LlmClient{


	private static final Logger logger = LoggerFactory.getLogger(OllamaLlmClient.class);
	
	private RestClient restClient;
	
	private final String model ; 
	
	
	 public OllamaLlmClient(
	            @Value("${ollama.base-url:http://localhost:11434}") String baseUrl,
	            @Value("${ollama.model:qwen3:8b}") String model) {
	        this.restClient = RestClient.builder()
	                .baseUrl(baseUrl)
	                .build();
	        this.model = model;
	        logger.info("OllamaLlmClient 초기화 - baseUrl={}, model={}", baseUrl, model);
	    }
	
	
	@Override
	public String generate(String systemPrompt, String userPrompt) {
		//모델 특징 튜닝(요청 body애 요구사항 다 적습니다)
		Map<String , Object> body  =Map.of(
				"model", model,
				"think", false,
				"stream",false,
				"messages",List.of(
						Map.of("role", "system",
								"content", systemPrompt),
						Map.of( "role","user",
								"content",userPrompt)
						),
				
				"options", Map.of(
						"temperature",0.3,
						"num_ctx",8192
						)
				);
				
		 try {
	            OllamaChatResponse res = restClient.post()
	                    .uri("/api/chat")
	                    .body(body)
	                    .retrieve()
	                    .body(OllamaChatResponse.class);

	            if (res == null || res.message() == null) {
	                throw new IllegalStateException("Ollama 응답이 비어있습니다.");
	            }
	            return res.message().content();

	        } catch (Exception e) {
	        	logger.error("Ollama 호출 실패: {}", e.getMessage());
	            throw new IllegalStateException("LLM 생성 실패 - Ollama 서버(11434) 확인 필요", e);
	        }
		 
	}
	
	
	 public record OllamaChatResponse(Message message) {
	        public record Message(String role, String content) {}
	    }
	
}
