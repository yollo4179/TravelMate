package com.yollo.TravelMate.domain.conversation.pipeline;

import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService.RankingMode;
import java.util.Objects;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public record ConversationModuleConfig(
        @Value("${travelmate.conversation.modules.search:KAFKA_V1}") SearchModule.Version search,
        @Value("${travelmate.conversation.modules.evidence:ORIGINAL_V1}") EvidenceModule.Version evidence,
        @Value("${travelmate.conversation.modules.prompt:RESOURCE_V1}") PromptModule.Version prompt,
        @Value("${travelmate.conversation.modules.model:GUARDED_V1}") ModelModule.Version model,
        @Value("${travelmate.conversation.modules.search-ranking:REQUEST_DEFAULT}") SearchRanking searchRanking,
        @Value("${travelmate.conversation.modules.prompt-resource:classpath:conversation/prompts/v2-grounded-system.txt}") String promptResource
) {
    public enum SearchRanking {
        REQUEST_DEFAULT(null),
        SEMANTIC_ONLY(RankingMode.SEMANTIC_ONLY),
        RERANKED(RankingMode.RERANKED);

        private final RankingMode selected;

        SearchRanking(RankingMode selected) {
            this.selected = selected;
        }

        public RankingMode resolve(RankingMode requested) {
            return Optional.ofNullable(selected).orElse(requested);
        }
    }

    public ConversationModuleConfig {
        Objects.requireNonNull(search);
        Objects.requireNonNull(evidence);
        Objects.requireNonNull(prompt);
        Objects.requireNonNull(model);
        Objects.requireNonNull(searchRanking);
        if (promptResource == null || promptResource.isBlank()) {
            throw new IllegalArgumentException("Conversation prompt resource must be explicit");
        }
        if (!promptResource.startsWith("classpath:") && !promptResource.startsWith("file:")) {
            throw new IllegalArgumentException("Conversation prompts must be local classpath or file resources");
        }
    }

    public static ConversationModuleConfig defaults() {
        return new ConversationModuleConfig(
                SearchModule.Version.KAFKA_V1,
                EvidenceModule.Version.ORIGINAL_V1,
                PromptModule.Version.RESOURCE_V1,
                ModelModule.Version.GUARDED_V1,
                SearchRanking.REQUEST_DEFAULT,
                "classpath:conversation/prompts/v2-grounded-system.txt"
        );
    }
}
