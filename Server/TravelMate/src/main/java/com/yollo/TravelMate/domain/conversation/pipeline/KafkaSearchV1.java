package com.yollo.TravelMate.domain.conversation.pipeline;

import com.yollo.TravelMate.domain.conversation.tool.PlaceSearchCriteriaResolver.Resolved;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class KafkaSearchV1 implements SearchModule {
    private final PlaceSemanticSearchService searches;

    @Override
    public boolean supports(Version version) {
        return version == Version.KAFKA_V1;
    }

    @Override
    public Batch execute(Resolved input, ConversationModuleConfig config) {
        var original = input.criteria();
        var criteria = new PlaceSearchRequest(
                original.query(),
                original.region(),
                original.city(),
                original.category(),
                original.excludePlaceIds(),
                original.area(),
                original.limit(),
                config.searchRanking().resolve(original.rankingMode())
        );
        var resolved = new Resolved(criteria, input.provenance());
        return new Batch(resolved, searches.search(criteria));
    }
}
