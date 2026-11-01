package com.yollo.TravelMate.ai.llm.derived;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.ai.llm.base.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class OpenAiLlmClient implements LlmStrategy {
    private final RestClient restClient;
    private final String model;
    private final String apiKey;
    private final int maxOutputTokens;

    @Autowired
    public OpenAiLlmClient(
            @Value("${openai.base-url:https://api.openai.com/v1}") String baseUrl,
            @Value("${openai.model:}") String model,
            @Value("${openai.api-key:}") String apiKey,
            @Value("${openai.max-output-tokens:1536}") int maxOutputTokens
    ) {
        this(LlmHttpClients.create(baseUrl), model, apiKey, maxOutputTokens);
    }

    public OpenAiLlmClient(
            RestClient restClient,
            String model,
            String apiKey,
            int maxOutputTokens
    ) {
        this.restClient = restClient;
        this.model = model;
        this.apiKey = apiKey;
        this.maxOutputTokens = maxOutputTokens;
    }

    @Override
    public boolean supports(LlmProvider provider) {
        return provider == LlmProvider.OPENAI;
    }

    @Override
    public String generate(String systemPrompt, String userPrompt) {
        var response = complete(List.of(
                LlmMessage.text(LlmMessage.Role.SYSTEM, systemPrompt),
                LlmMessage.text(LlmMessage.Role.USER, userPrompt)
        ), List.of(), true);
        if (!response.toolCalls().isEmpty()) throw new IllegalStateException("계획 JSON 대신 도구 호출을 반환했습니다.");
        return response.content();
    }

    @Override
    public LlmTurn chat(List<LlmMessage> messages, List<LlmTurn.ToolDefinition> tools) {
        return complete(messages, tools, false);
    }

    private LlmTurn complete(
            List<LlmMessage> messages,
            List<LlmTurn.ToolDefinition> tools,
            boolean jsonOutput
    ) {
        if (model.isBlank() || apiKey.isBlank() || maxOutputTokens < 1) {
            throw new IllegalStateException("OpenAI 모델·API 키·출력 토큰 설정이 필요합니다.");
        }
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("model", model);
        request.put("input", messages.stream().flatMap(message -> wireItems(message).stream()).toList());
        request.put("stream", false);
        request.put("store", false);
        request.put("truncation", "disabled");
        request.put("max_output_tokens", maxOutputTokens);
        request.put("include", List.of("reasoning.encrypted_content"));
        if (jsonOutput) request.put("text", Map.of("format", Map.of("type", "json_object")));
        if (!tools.isEmpty()) {
            request.put("tools", tools.stream().map(tool -> Map.of(
                    "type", "function",
                    "name", tool.name(),
                    "description", tool.description(),
                    "parameters", tool.parameters(),
                    "strict", true
            )).toList());
            request.put("parallel_tool_calls", false);
        }
        final JsonNode response;
        try {
            response = restClient.post().uri("/responses")
                    .header("Authorization", "Bearer " + apiKey)
                    .body(request).retrieve().body(JsonNode.class);
        } catch (RuntimeException exception) {
            // 공급자 오류 본문이나 인증 헤더를 외부 응답·작업 실패 사유에 노출하지 않는다.
            throw new IllegalStateException("OpenAI 서버 호출에 실패했습니다.");
        }
        if (response == null || !"completed".equals(response.path("status").asText())
                || !response.path("output").isArray()) {
            throw new IllegalStateException("OpenAI 응답이 비어 있거나 완료되지 않았습니다.");
        }
        StringBuilder content = new StringBuilder();
        List<LlmTurn.ToolCall> calls = new ArrayList<>();
        List<JsonNode> continuation = new ArrayList<>();
        response.get("output").forEach(item -> {
            continuation.add(item.deepCopy());
            if ("function_call".equals(item.path("type").asText())) {
                calls.add(new LlmTurn.ToolCall(
                        item.path("call_id").asText(),
                        item.path("name").asText(),
                        item.path("arguments").asText()
                ));
            }
            if ("message".equals(item.path("type").asText())) {
                item.path("content").forEach(part -> {
                    if ("refusal".equals(part.path("type").asText())) {
                        throw new IllegalStateException("OpenAI 모델이 응답을 거부했습니다.");
                    }
                    if ("output_text".equals(part.path("type").asText())) content.append(part.path("text").asText());
                });
            }
        });
        return LlmTurn.builder().content(content.toString()).toolCalls(calls).continuation(continuation).build();
    }

    private List<Object> wireItems(LlmMessage message) {
        if (message.role() == LlmMessage.Role.TOOL) {
            return List.of(Map.of("type", "function_call_output", "call_id", message.toolCallId(), "output", message.content()));
        }
        if (!message.continuation().isEmpty()) return new ArrayList<>(message.continuation());
        return List.of(Map.of("role", message.role().name().toLowerCase(Locale.ROOT), "content", message.content()));
    }
}
