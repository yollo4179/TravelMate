package com.yollo.TravelMate.ai.llm.derived;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.observation.ExecutionRecorder;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.service.ConversationAnswerContract;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class OpenAiLlmClient implements LlmStrategy {
    private static final ObjectMapper JSON = new ObjectMapper();
    private final RestClient restClient;
    private final String model;
    private final String apiKey;
    private final int maxOutputTokens;
    private final TokenBudget.Limits limits;
    private final LlmCallGuard guard;
    private final OpenAiToolContracts.Mode toolContractMode;
    private final OpenAiBatchBudget batchBudget;
    private final ConversationResponseFormat responseFormat;
    private BatchBudgetRequirement budgetRequirement;
    private ReasoningMode reasoningMode = ReasoningMode.DISABLED;
    private InputCountPolicy inputCountPolicy = InputCountPolicy.PROVIDER_ALWAYS;

    @Autowired
    public OpenAiLlmClient(
            @Value("${openai.base-url:https://api.openai.com/v1}") String baseUrl,
            @Value("${openai.model:}") String model,
            @Value("${openai.api-key:}") String apiKey,
            @Value("${openai.max-output-tokens:1536}") int maxOutputTokens,
            @Value("${openai.context-tokens:0}") long contextTokens,
            @Value("${openai.model-output-limit:0}") long modelOutputLimit,
            @Value("${openai.limits-model:}") String limitsModel,
            @Value("${openai.limits-source:}") String limitsSource,
            @Value("${openai.tool-contract-mode:CANONICAL}") OpenAiToolContracts.Mode toolContractMode,
            @Value("${openai.conversation-response-format:PROMPT_ONLY}") ConversationResponseFormat responseFormat,
            @Value("${openai.reasoning-mode:DISABLED}") ReasoningMode reasoningMode,
            @Value("${openai.evaluation-budget-requirement:OPTIONAL}") BatchBudgetRequirement budgetRequirement,
            @Value("${openai.input-count-policy:PROVIDER_ALWAYS}") InputCountPolicy inputCountPolicy,
            OpenAiBatchBudget batchBudget,
            LlmCallGuard guard
    ) {
        this(LlmHttpClients.create(baseUrl), apiKey, TokenBudget.Limits.builder()
                .provider(LlmProvider.OPENAI).model(model).contextTokens(contextTokens).outputReservation(maxOutputTokens)
                .modelOutputLimit(modelOutputLimit).limitsModel(limitsModel).limitsSource(limitsSource).build(), guard, toolContractMode, batchBudget, responseFormat);
        this.reasoningMode = java.util.Objects.requireNonNull(reasoningMode);
        this.budgetRequirement = java.util.Objects.requireNonNull(budgetRequirement);
        this.inputCountPolicy = java.util.Objects.requireNonNull(inputCountPolicy);
    }

    /** Selects how inputs are bounded before dispatch; the default keeps the provider count on every call. */
    public OpenAiLlmClient inputCountPolicy(InputCountPolicy policy) {
        this.inputCountPolicy = java.util.Objects.requireNonNull(policy);
        return this;
    }

    public OpenAiLlmClient(
            RestClient restClient,
            String model,
            String apiKey,
            int maxOutputTokens
    ) {
        this(restClient, apiKey, TokenBudget.Limits.builder().provider(LlmProvider.OPENAI).model(model)
                .outputReservation(maxOutputTokens).build(),
                new LlmCallGuard(JSON, new ExecutionRecorder("build/observations")));
    }

    public OpenAiLlmClient(
            RestClient restClient,
            String apiKey,
            TokenBudget.Limits limits,
            LlmCallGuard guard
    ) {
        this(restClient, apiKey, limits, guard, OpenAiToolContracts.Mode.CANONICAL);
    }

    public OpenAiLlmClient(
            RestClient restClient,
            String apiKey,
            TokenBudget.Limits limits,
            LlmCallGuard guard,
            OpenAiToolContracts.Mode toolContractMode
    ) {
        this(restClient, apiKey, limits, guard, toolContractMode, new OpenAiBatchBudget(""));
    }

    public OpenAiLlmClient(
            RestClient restClient,
            String apiKey,
            TokenBudget.Limits limits,
            LlmCallGuard guard,
            OpenAiToolContracts.Mode toolContractMode,
            OpenAiBatchBudget batchBudget
    ) {
        this(restClient, apiKey, limits, guard, toolContractMode, batchBudget, ConversationResponseFormat.PROMPT_ONLY);
    }

    public OpenAiLlmClient(
            RestClient restClient,
            String apiKey,
            TokenBudget.Limits limits,
            LlmCallGuard guard,
            OpenAiToolContracts.Mode toolContractMode,
            OpenAiBatchBudget batchBudget,
            ConversationResponseFormat responseFormat
    ) {
        this.restClient = restClient;
        this.model = limits.model();
        this.apiKey = apiKey;
        this.maxOutputTokens = Math.toIntExact(limits.outputReservation());
        this.limits = limits;
        this.guard = guard;
        this.toolContractMode = toolContractMode;
        this.batchBudget = batchBudget;
        this.budgetRequirement = toolContractMode == OpenAiToolContracts.Mode.STRICT_SEARCH_V1
                ? BatchBudgetRequirement.REQUIRED : BatchBudgetRequirement.OPTIONAL;
        this.responseFormat = java.util.Objects.requireNonNull(responseFormat);
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
        return complete(messages, tools, false, null);
    }

    @Override
    public LlmTurn chat(List<LlmMessage> messages, List<LlmTurn.ToolDefinition> tools, StructuredOutput output) {
        return complete(messages, tools, false, output);
    }

    private LlmTurn complete(
            List<LlmMessage> messages,
            List<LlmTurn.ToolDefinition> tools,
            boolean jsonOutput
    ) {
        return complete(messages, tools, jsonOutput, null);
    }

    private LlmTurn complete(
            List<LlmMessage> messages,
            List<LlmTurn.ToolDefinition> tools,
            boolean jsonOutput,
            StructuredOutput output
    ) {
        var preparedTools = OpenAiToolContracts.prepare(tools, toolContractMode);
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("model", model);
        request.put("input", messages.stream().flatMap(message -> wireItems(message).stream()).toList());
        request.put("stream", false);
        request.put("store", false);
        request.put("service_tier", "default");
        request.put("truncation", "disabled");
        request.put("max_output_tokens", maxOutputTokens);
        if (reasoningMode == ReasoningMode.DISABLED) request.put("reasoning", Map.of("effort", "none"));
        if (jsonOutput) request.put("text", Map.of("format", responseFormat == ConversationResponseFormat.JSON_SCHEMA_V1
                ? Map.of("type", "json_schema", "name", "draft_plan_v1", "strict", true,
                    "schema", com.yollo.TravelMate.domain.plan.prompts.GeneratedPlanOutputContract.schema())
                : Map.of("type", "json_object")));
        if (output != null) {
            // An explicit caller schema wins: the LiLi turn needs Strict JSON even when it is offered no tools.
            request.put("text", Map.of("format", Map.of(
                    "type", "json_schema",
                    "name", output.name(),
                    "strict", true,
                    "schema", output.schema()
            )));
        } else if (!jsonOutput && !tools.isEmpty() && responseFormat == ConversationResponseFormat.JSON_SCHEMA_V1) {
            request.put("text", Map.of("format", Map.of(
                    "type", "json_schema",
                    "name", "conversation_answer_v1",
                    "strict", true,
                    "schema", ConversationAnswerContract.schema()
            )));
        }
        if (!tools.isEmpty()) {
            request.put("tools", preparedTools.stream().map(tool -> Map.of(
                    "type", "function",
                    "name", tool.definition().name(),
                    "description", tool.definition().description(),
                    "parameters", tool.parameters(),
                    "strict", tool.strict()
            )).toList());
            request.put("parallel_tool_calls", false);
        }
        JsonNode wireRequest = JSON.valueToTree(request);
        var reservation = new java.util.concurrent.atomic.AtomicReference<OpenAiBatchBudget.Reservation>();
        var countedInput = new java.util.concurrent.atomic.AtomicReference<TokenBudget.Count>();
        try {
            return guard.call(limits, wireRequest, () -> {
                    if (budgetRequirement == BatchBudgetRequirement.REQUIRED) batchBudget.requireConfigured();
                    reservation.set(batchBudget.reserve(limits));
                    var counted = countInput(wireRequest);
                    countedInput.set(counted);
                    return counted;
                },
                () -> infer(request), this::receipt, response -> {
                    batchBudget.verifyProvider(reservation.get(), response);
                    batchBudget.observe(reservation.get(), receipt(response), countedInput.get());
                    return decode(response, preparedTools);
                });
        } catch (RuntimeException exception) {
            batchBudget.halt(reservation.get());
            throw exception;
        }
    }

    private TokenBudget.Count countInput(JsonNode wireRequest) {
        var countRequest = JSON.createObjectNode();
        for (String name : List.of("model", "input", "tools", "text", "parallel_tool_calls")) {
            if (wireRequest.has(name)) countRequest.set(name, wireRequest.get(name));
        }
        return InputCountMethod.count(inputCountPolicy, countRequest, limits, () -> providerCount(countRequest));
    }

    private TokenBudget.Count providerCount(JsonNode countRequest) {
        if (apiKey.isBlank()) throw new IllegalStateException("OpenAI API 키 설정이 필요합니다.");
        JsonNode count = restClient.post().uri("/responses/input_tokens")
                .header("Authorization", "Bearer " + apiKey).body(countRequest).retrieve().body(JsonNode.class);
        Long tokens = count == null ? null : TokenBudget.reported(count, "input_tokens");
        if (tokens == null || !"response.input_tokens".equals(count.path("object").asText())) {
            throw new IllegalStateException("OpenAI 입력 토큰 확인값이 없습니다.");
        }
        return new TokenBudget.Count(tokens, TokenBudget.Quality.CONFIRMED_API,
                "OPENAI_RESPONSES_INPUT_TOKENS", null, count);
    }

    private JsonNode infer(Map<String, Object> request) {
        try {
            return restClient.post().uri("/responses")
                    .header("Authorization", "Bearer " + apiKey)
                    .body(request).retrieve().body(JsonNode.class);
        } catch (RuntimeException exception) {
            // 공급자 오류 본문이나 인증 헤더를 외부 응답·작업 실패 사유에 노출하지 않는다.
            throw new IllegalStateException("OpenAI 서버 호출에 실패했습니다.");
        }
    }

    private TokenBudget.Receipt receipt(JsonNode response) {
        var usage = response.path("usage");
        var calls = JSON.createArrayNode();
        response.path("output").forEach(item -> {
            if ("function_call".equals(item.path("type").asText())) calls.add(item.deepCopy());
        });
        return new TokenBudget.Receipt(new TokenBudget.Usage(
                TokenBudget.reported(usage, "input_tokens"), TokenBudget.reported(usage, "output_tokens"),
                TokenBudget.reported(usage.path("output_tokens_details"), "reasoning_tokens"),
                TokenBudget.reported(usage.path("input_tokens_details"), "cached_tokens")
        ), calls, response.path("status").asText(null));
    }

    private LlmTurn decode(JsonNode response, List<OpenAiToolContracts.PreparedTool> tools) {
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
                var nativeCall = new LlmTurn.ToolCall(
                        item.path("call_id").asText(),
                        item.path("name").asText(),
                        item.path("arguments").asText()
                );
                calls.add(tools.stream().filter(tool -> tool.definition().name().equals(nativeCall.name())).findFirst()
                        .map(tool -> tool.adapt(nativeCall)).orElse(nativeCall));
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
