package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.IntStream;
import java.util.stream.StreamSupport;
import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;

/** Execution facts stay visible even when no candidate has an original that LiLi can cite. */
public final class RecommendationExecutionFacts {
    private RecommendationExecutionFacts() {}

    public enum ExclusionStatus { NOT_REQUESTED, VERIFIED, UNVERIFIED }

    public record Location(String region, String city) {}

    public record Facts(
            List<Location> returnedLocations,
            long unknownLocationCount,
            ExclusionStatus exclusionStatus,
            List<Integer> excludedDisplayedPositions
    ) {}

    public static Facts execute(
            ConversationRequest request,
            ConversationEvidencePreparation.Prepared prepared
    ) {
        var result = prepared.result();
        JsonNode cards = result == null ? null : result.publicData();
        List<JsonNode> places = cards != null && cards.isArray()
                ? StreamSupport.stream(cards.spliterator(), false).toList() : List.of();
        List<Location> locations = places.stream()
                .map(place -> new Location(text(place, "region"), text(place, "city")))
                .distinct().toList();
        long unknown = places.stream().filter(place -> text(place, "region") == null).count();
        List<Long> requested = request.searchContext() == null ? List.of() : request.searchContext().excludePlaceIds();
        if (requested.isEmpty()) return new Facts(locations, unknown, ExclusionStatus.NOT_REQUESTED, List.of());

        JsonNode criteria = result == null || result.modelData() == null ? null : result.modelData().path("searchCriteria");
        JsonNode applied = criteria == null ? null : criteria.path("excludePlaceIds");
        Set<Long> appliedIds = applied != null && applied.isArray()
                ? StreamSupport.stream(applied.spliterator(), false).filter(JsonNode::isIntegralNumber)
                        .map(JsonNode::longValue).collect(Collectors.toSet()) : Set.of();
        boolean completed = prepared.state() == ConversationEvidencePreparation.State.READY
                || prepared.state() == ConversationEvidencePreparation.State.EMPTY;
        boolean verified = completed && appliedIds.containsAll(requested)
                && places.stream().allMatch(place -> place.path("placeId").isIntegralNumber()
                        && !requested.contains(place.path("placeId").longValue()));
        List<Long> displayed = request.displayedResult() == null ? List.of() : request.displayedResult().placeIds();
        List<Integer> positions = verified ? IntStream.range(0, displayed.size())
                .filter(index -> requested.contains(displayed.get(index))).map(index -> index + 1).boxed().toList() : List.of();
        return new Facts(locations, unknown, verified ? ExclusionStatus.VERIFIED : ExclusionStatus.UNVERIFIED, positions);
    }

    private static String text(JsonNode place, String field) {
        JsonNode value = place.path(field);
        return value.isTextual() && !value.textValue().isBlank() ? value.textValue() : null;
    }
}
