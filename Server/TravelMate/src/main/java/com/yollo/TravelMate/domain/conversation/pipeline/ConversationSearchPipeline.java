package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.List;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.PlaceSearchCriteriaResolver.Resolved;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import org.springframework.stereotype.Component;

@Component
public class ConversationSearchPipeline {
    private final SearchModule search;
    private final EvidenceModule evidence;
    private final ConversationModuleConfig config;

    public ConversationSearchPipeline(
            List<SearchModule> searches,
            List<EvidenceModule> evidenceBuilders,
            ConversationModuleConfig config
    ) {
        this.config = config;
        search = ModuleSelection.requireOne(searches, module -> module.supports(config.search()), "search");
        evidence = ModuleSelection.requireOne(evidenceBuilders, module -> module.supports(config.evidence()), "evidence");
    }

    public ConversationTool.Result execute(Resolved input) {
        return evidence.execute(search.execute(input, config), config);
    }

    public static ConversationSearchPipeline defaults(
            PlaceSemanticSearchService searches,
            ContextPlanPromptFactory prompts,
            ObjectMapper mapper
    ) {
        return new ConversationSearchPipeline(
                List.of(new KafkaSearchV1(searches)),
                List.of(new OriginalEvidenceV1(prompts, mapper)),
                ConversationModuleConfig.defaults()
        );
    }
}
