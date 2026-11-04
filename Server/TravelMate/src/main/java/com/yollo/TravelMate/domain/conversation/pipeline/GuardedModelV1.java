package com.yollo.TravelMate.domain.conversation.pipeline;

import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class GuardedModelV1 implements ModelModule {
    private final LlmClient client;

    @Override
    public boolean supports(Version version) {
        return version == Version.GUARDED_V1;
    }

    @Override
    public LlmTurn execute(Input input, ConversationModuleConfig config) {
        // Keep provider selection, exact counting, reservations and usage accounting on the existing path.
        if (input.output() == null) return client.chat(input.messages(), input.tools());
        return client.chat(input.messages(), input.tools(), input.output());
    }
}
