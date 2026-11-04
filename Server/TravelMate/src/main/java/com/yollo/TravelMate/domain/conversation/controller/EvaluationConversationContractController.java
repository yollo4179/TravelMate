package com.yollo.TravelMate.domain.conversation.controller;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import com.yollo.TravelMate.ai.llm.base.LlmProvider;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationGenerationPipeline;
import com.yollo.TravelMate.domain.conversation.service.ConversationAnswerContract;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import com.yollo.TravelMate.domain.user.entity.User;
import lombok.RequiredArgsConstructor;

@Profile("evaluation")
@RestController
@RequestMapping("/api/evaluation")
@RequiredArgsConstructor
public class EvaluationConversationContractController {
    private final ConversationToolRegistry tools;
    private final ConversationGenerationPipeline generation;
    private final Environment environment;

    @GetMapping("/conversation-contract")
    public Map<String, Object> contract(@AuthenticationPrincipal User user) {
        var provider = environment.getProperty("llm.provider", LlmProvider.class, LlmProvider.OPENAI);
        var modelProperty = Map.of(LlmProvider.OPENAI, "openai.model", LlmProvider.QWEN, "ollama.model").get(provider);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("schema_version", "conversation-evaluation-contract-v1");
        result.put("environment", "evaluation");
        result.put("evaluation_user", Map.of("user_id", user.getUserId(), "uid", user.getUid()));
        result.put("tools", tools.definitions().stream().map(definition -> Map.of(
                "tool_type", Arrays.stream(ConversationTool.Name.values())
                        .filter(name -> name.wireName().equals(definition.name())).findFirst().orElseThrow().name(),
                "name", definition.name(),
                "parameters", definition.parameters()
        )).toList());
        result.put("answer_schema", ConversationAnswerContract.schema());
        result.put("max_model_turns", environment.getRequiredProperty("travelmate.conversation.max-model-turns", Integer.class));
        result.put("max_tool_calls", environment.getRequiredProperty("travelmate.conversation.max-tool-calls", Integer.class));
        result.put("provider", provider.name());
        result.put("model", environment.getProperty(modelProperty, ""));
        var formatProperty = Map.of(LlmProvider.OPENAI, "openai.conversation-response-format",
                LlmProvider.QWEN, "ollama.conversation-response-format").get(provider);
        result.put("response_format", environment.getProperty(formatProperty, "PROMPT_ONLY"));
        result.put("modules", generation.selection());
        result.put("search_endpoint", environment.getProperty("embedding.server.url", "http://127.0.0.1:18000"));
        result.put("source_sha256", com.yollo.TravelMate.domain.conversation.pipeline.RuntimeBuildIdentity.sourceSha256());
        result.put("reasoning_mode", environment.getProperty("openai.reasoning-mode", "DISABLED"));
        result.put("evaluation_budget_requirement", environment.getProperty("openai.evaluation-budget-requirement", "REQUIRED"));
        result.put("tool_contract_mode", environment.getProperty("openai.tool-contract-mode", "STRICT_TOOLS_V1"));
        result.put("observation_file", java.nio.file.Path.of(environment.getProperty(
                "travelmate.observation.directory", "build/observations")).resolve("execution.jsonl").toAbsolutePath().normalize().toString());
        return result;
    }
}
