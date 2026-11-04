package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.List;
import com.yollo.TravelMate.domain.conversation.tool.PlaceSearchCriteriaResolver.Resolved;
import com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult;

public interface SearchModule {
    enum Version { KAFKA_V1 }

    record Batch(Resolved resolved, List<PlaceSemanticSearchResult> results) {
        public Batch {
            results = List.copyOf(results);
        }
    }

    boolean supports(Version version);

    Batch execute(Resolved input, ConversationModuleConfig config);
}
