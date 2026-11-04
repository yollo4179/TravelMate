package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.List;
import java.util.Map;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import org.springframework.core.io.DefaultResourceLoader;
import org.springframework.stereotype.Component;

@Component
public class ConversationGenerationPipeline {
    private final PromptModule prompt;
    private final ModelModule model;
    private final ConversationModuleConfig config;

    public ConversationGenerationPipeline(
            List<PromptModule> prompts,
            List<ModelModule> models,
            ConversationModuleConfig config
    ) {
        this.config = config;
        prompt = ModuleSelection.requireOne(prompts, module -> module.supports(config.prompt()), "prompt");
        model = ModuleSelection.requireOne(models, module -> module.supports(config.model()), "model");
    }

    public String systemPrompt(ConversationRequest request) {
        return prompt.execute(request, config);
    }

    public LlmTurn execute(ModelModule.Input input) {
        return model.execute(input, config);
    }

    public ConversationModuleConfig config() {
        return config;
    }

    public Map<String, Object> selection() {
        return Map.of(
                "config", config,
                "promptClass", prompt.getClass().getName(),
                "promptSha256", prompt.sha256(),
                "modelClass", model.getClass().getName()
        );
    }

    public static ConversationGenerationPipeline defaults(LlmClient client) {
        var config = ConversationModuleConfig.defaults();
        return new ConversationGenerationPipeline(
                List.of(new ResourcePromptV1(config, new DefaultResourceLoader())),
                List.of(new GuardedModelV1(client)),
                config
        );
    }
}
