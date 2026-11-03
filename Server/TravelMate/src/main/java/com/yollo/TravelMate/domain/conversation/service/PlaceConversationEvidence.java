package com.yollo.TravelMate.domain.conversation.service;

import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class PlaceConversationEvidence implements ConversationEvidenceStrategy {
    private final ObjectMapper mapper;

    @Override
    public boolean supports(ConversationToolRegistry registry) {
        return registry.definitions().stream().anyMatch(definition -> source().wireName().equals(definition.name()));
    }

    @Override
    public ConversationTool.Name source() {
        return ConversationTool.Name.SEARCH_PLACES;
    }

    @Override
    public ConversationTool.Result prepare(
            String userUid,
            UUID turnKey,
            ConversationRequest request,
            ConversationToolRegistry registry
    ) {
        var arguments = mapper.createObjectNode().put("query", request.message());
        return registry.resolve(source().wireName()).execute(ConversationTool.Invocation.builder()
                .userUid(userUid)
                .turnKey(turnKey)
                .request(request)
                .arguments(arguments)
                .build());
    }
}
