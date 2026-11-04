package com.yollo.TravelMate.domain.conversation.service;

import java.util.Map;
import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.pipeline.PromptTemplates;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Component;

@Component
public class PlaceConversationEvidence implements ConversationEvidenceStrategy {
    private static final String THEME_SEPARATOR = ", ";
    private final ObjectMapper mapper;
    private final String themeHintTemplate;

    public PlaceConversationEvidence(
            ObjectMapper mapper,
            ResourceLoader resources,
            @Value("${travelmate.conversation.evidence.theme-hint-resource:classpath:conversation/queries/v1-theme-hint.txt}")
            String themeHintResource
    ) {
        this.mapper = mapper;
        // Themes are a semantic preference, not a DB filter, so they only enrich the pre-retrieval query text.
        this.themeHintTemplate = PromptTemplates.load(resources, themeHintResource).stripTrailing();
    }

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
        var arguments = mapper.createObjectNode().put("query", query(request));
        return registry.resolve(source().wireName()).execute(ConversationTool.Invocation.builder()
                .userUid(userUid)
                .turnKey(turnKey)
                .request(request)
                .arguments(arguments)
                .build());
    }

    private String query(ConversationRequest request) {
        if (request.searchContext() == null || request.searchContext().themes().isEmpty()) return request.message();
        return PromptTemplates.render(themeHintTemplate, Map.of(
                "message", request.message(),
                "themes", String.join(THEME_SEPARATOR, request.searchContext().themes())
        ));
    }
}
