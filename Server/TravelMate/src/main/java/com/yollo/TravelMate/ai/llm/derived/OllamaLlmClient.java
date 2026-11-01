package com.yollo.TravelMate.ai.llm.derived;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.observation.ExecutionRecorder;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class OllamaLlmClient implements LlmStrategy {
    private static final com.fasterxml.jackson.databind.ObjectMapper JSON = new com.fasterxml.jackson.databind.ObjectMapper();
    private final RestClient restClient;
    private final String model;
    private final TokenBudget.Limits limits;
    private final LlmCallGuard guard;

    @Autowired
    public OllamaLlmClient(
            @Value("${ollama.base-url:http://localhost:11434}") String baseUrl,
            @Value("${ollama.model:qwen3:8b}") String model,
            @Value("${ollama.context-tokens:8192}") int contextTokens,
            @Value("${ollama.max-output-tokens:1536}") int outputTokens,
            LlmCallGuard guard
    ) {
        this(LlmHttpClients.create(baseUrl), model, contextTokens, outputTokens, guard);
    }

    public OllamaLlmClient(RestClient restClient, String model) {
        this(restClient, model, 8192, 1536,
                new LlmCallGuard(JSON, new ExecutionRecorder("build/observations")));
    }

    public OllamaLlmClient(
            RestClient restClient,
            String model,
            int contextTokens,
            int outputTokens,
            LlmCallGuard guard
    ) {
        this.restClient = restClient;
        this.model = model;
        this.guard = guard;
        this.limits = TokenBudget.Limits.builder().provider(LlmProvider.QWEN).model(model)
                .contextTokens(contextTokens).outputReservation(outputTokens).modelOutputLimit(contextTokens)
                .limitsModel(model).limitsSource("configured num_ctx/output; api/show native ceiling and template checked per call").build();
    }

    @Override
    public boolean supports(LlmProvider provider) {
        return provider == LlmProvider.QWEN;
    }

    @Override
    public String generate(String systemPrompt, String userPrompt) {
        return complete(List.of(
                LlmMessage.text(LlmMessage.Role.SYSTEM, systemPrompt),
                LlmMessage.text(LlmMessage.Role.USER, userPrompt)
        ), List.of(), true).content();
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
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("model", model);
        request.put("think", false);
        request.put("stream", false);
        request.put("messages", messages.stream().map(this::wireMessage).toList());
        request.put("options", Map.of("temperature", 0.3, "num_ctx", limits.contextTokens(), "num_predict", limits.outputReservation()));
        if (jsonOutput) request.put("format", "json");
        if (!tools.isEmpty()) {
            request.put("tools", tools.stream().map(tool -> Map.of(
                    "type", "function",
                    "function", Map.of("name", tool.name(), "description", tool.description(), "parameters", tool.parameters())
            )).toList());
        }
        JsonNode wireRequest = JSON.valueToTree(request);
        return guard.call(limits, wireRequest, () -> QwenTokenCounter.count(restClient, wireRequest),
                () -> infer(request), this::receipt, this::decode);
    }

    private JsonNode infer(Map<String, Object> request) {
        try {
            return restClient.post().uri("/api/chat").body(request).retrieve().body(JsonNode.class);
        } catch (RuntimeException exception) {
            throw new IllegalStateException("Qwen 서버 호출에 실패했습니다.");
        }
    }

    private TokenBudget.Receipt receipt(JsonNode response) {
        return new TokenBudget.Receipt(new TokenBudget.Usage(
                TokenBudget.reported(response, "prompt_eval_count"), TokenBudget.reported(response, "eval_count"),
                null, TokenBudget.reported(response, "prompt_eval_cached_count")
        ), response.path("message").get("tool_calls"), response.path("done_reason").asText(null));
    }

    private LlmTurn decode(JsonNode response) {
        if (response == null || !response.path("done").asBoolean()
                || "length".equals(response.path("done_reason").asText())
                || !response.path("message").isObject()
                || !"assistant".equals(response.path("message").path("role").asText())) {
            throw new IllegalStateException("Qwen 응답이 비어 있거나 완료되지 않았습니다.");
        }
        JsonNode assistant = response.get("message");
        List<LlmTurn.ToolCall> calls = new ArrayList<>();
        JsonNode toolCalls = assistant.path("tool_calls");
        if (!toolCalls.isMissingNode() && !toolCalls.isArray()) {
            throw new IllegalStateException("Qwen 도구 호출 형식이 올바르지 않습니다.");
        }
        toolCalls.forEach(call -> {
            JsonNode function = call.path("function");
            JsonNode arguments = function.path("arguments");
            String serialized = arguments.isTextual() ? arguments.textValue() : arguments.toString();
            calls.add(new LlmTurn.ToolCall(
                    UUID.randomUUID().toString(),
                    function.path("name").asText(),
                    serialized
            ));
        });
        return LlmTurn.builder().content(assistant.path("content").asText("")).toolCalls(calls).build();
    }

    private Map<String, Object> wireMessage(LlmMessage message) {
        Map<String, Object> encoded = new LinkedHashMap<>();
        encoded.put("role", message.role().name().toLowerCase(java.util.Locale.ROOT));
        encoded.put("content", message.content() == null ? "" : message.content());
        if (message.role() == LlmMessage.Role.TOOL) encoded.put("tool_name", message.toolName());
        if (!message.toolCalls().isEmpty()) {
            encoded.put("tool_calls", message.toolCalls().stream().map(call -> Map.of(
                    "type", "function",
                    "function", Map.of("name", call.name(), "arguments", parsedArguments(call.arguments()))
            )).toList());
        }
        return encoded;
    }

    private JsonNode parsedArguments(String arguments) {
        try {
            return JSON.readTree(arguments);
        } catch (com.fasterxml.jackson.core.JsonProcessingException exception) {
            throw new IllegalStateException("Qwen 도구 인자를 다시 직렬화하지 못했습니다.");
        }
    }
}
