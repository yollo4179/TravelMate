package com.yollo.TravelMate.domain.conversation.pipeline;

import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Component;

@Component
public class ResourcePromptV1 implements PromptModule {
    private final String prompt;
    private final String fingerprint;

    public ResourcePromptV1(ConversationModuleConfig config, ResourceLoader resources) {
        prompt = PromptTemplates.render(PromptTemplates.load(resources, config.promptResource()), PromptVocabulary.tokens());
        // Fingerprint the text the model actually receives, after enum vocabulary is filled in.
        fingerprint = PromptTemplates.sha256(prompt);
    }

    @Override
    public boolean supports(Version version) {
        return version == Version.RESOURCE_V1;
    }

    @Override
    public String execute(ConversationRequest input, ConversationModuleConfig config) {
        return prompt;
    }

    @Override
    public String sha256() {
        return fingerprint;
    }
}
