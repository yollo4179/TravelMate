package com.yollo.TravelMate;

import java.util.List;
import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationIntent;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.data.DisplayedResult;
import com.yollo.TravelMate.domain.conversation.service.ConversationEvidencePreparation;
import com.yollo.TravelMate.domain.conversation.service.ConversationEvidencePreparation.State;
import com.yollo.TravelMate.domain.conversation.service.RecommendationExecutionFacts;
import com.yollo.TravelMate.domain.conversation.service.RecommendationExecutionFacts.ExclusionStatus;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchContext;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class RecommendationExecutionFactsTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final ConversationRequest request = new ConversationRequest("세 번째도 빼 줘.", null, List.of(),
            new PlaceSearchContext("서울", null, null, List.of(173L, 368L), null), ConversationIntent.AUTO,
            new DisplayedResult(UUID.randomUUID(), List.of(188L, 272L, 368L)));

    @Test
    void exactThirdPositionIsReportedOnlyAfterBothExistingAndNewExclusionsAreApplied() throws Exception {
        var facts = RecommendationExecutionFacts.execute(request, prepared(State.READY, "[173,368]", "[{\"placeId\":188}]"));
        assertEquals(ExclusionStatus.VERIFIED, facts.exclusionStatus());
        assertEquals(List.of(3), facts.excludedDisplayedPositions());
        assertEquals(1, facts.unknownLocationCount());
    }

    @Test
    void droppedExistingFilterOrLeakedExcludedPlaceCannotBeReportedAsCompleted() throws Exception {
        for (var prepared : List.of(prepared(State.READY, "[368]", "[{\"placeId\":188}]"),
                prepared(State.READY, "[173,368]", "[{\"placeId\":173}]"),
                prepared(State.READY, "null", "[{\"placeId\":188}]"))) {
            var facts = RecommendationExecutionFacts.execute(request, prepared);
            assertEquals(ExclusionStatus.UNVERIFIED, facts.exclusionStatus());
            assertTrue(facts.excludedDisplayedPositions().isEmpty());
        }
    }

    @Test
    void emptyCompletedSearchIsDifferentFromFailedSearch() throws Exception {
        assertEquals(ExclusionStatus.VERIFIED,
                RecommendationExecutionFacts.execute(request, prepared(State.EMPTY, "[173,368]", "[]")).exclusionStatus());
        assertEquals(ExclusionStatus.UNVERIFIED,
                RecommendationExecutionFacts.execute(request, prepared(State.FAILED, "[173,368]", "[]")).exclusionStatus());
    }

    @Test
    void actualMixedRegionsAreKeptInsteadOfInferringOneRegionFromTheRequest() throws Exception {
        var prepared = prepared(State.READY, "[173,368]", """
                [{"placeId":188,"region":"서울","city":"종로"},
                 {"placeId":300,"region":"부산","city":"해운대"},{"placeId":500}]
                """);
        var facts = RecommendationExecutionFacts.execute(request, prepared);
        assertEquals(List.of(new RecommendationExecutionFacts.Location("서울", "종로"),
                new RecommendationExecutionFacts.Location("부산", "해운대"),
                new RecommendationExecutionFacts.Location(null, null)), facts.returnedLocations());
        assertEquals(1, facts.unknownLocationCount());
    }

    private ConversationEvidencePreparation.Prepared prepared(State state, String excluded, String cards) throws Exception {
        var result = ConversationTool.Result.builder().type(ResultType.PLACES).publicData(mapper.readTree(cards))
                .modelData(mapper.readTree("{\"searchCriteria\":{\"excludePlaceIds\":" + excluded + "}}" )).build();
        return new ConversationEvidencePreparation.Prepared(state, ConversationTool.Name.SEARCH_PLACES, result);
    }
}
