package com.yollo.TravelMate.domain.conversation.tool;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Stream;
import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchContext;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService.RankingMode;
import org.springframework.stereotype.Component;

@Component
public class PlaceSearchCriteriaResolver {
    public enum Origin { TOOL_ARGUMENT, SEARCH_CONTEXT, LEGACY_PLAN_AREA, UNION, UNSPECIFIED }
    public record Resolved(PlaceSearchRequest criteria, Map<String, Origin> provenance) {}

    public Resolved resolve(ConversationRequest request, JsonNode arguments) {
        SearchPlacesContract.validate(arguments);
        var context = request.searchContext();
        Origin contextOrigin = Origin.SEARCH_CONTEXT;
        if (context == null && request.planningRequest() != null) {
            var area = request.planningRequest().context().area();
            if (area.type() != com.yollo.TravelMate.domain.plan.data.request.PlanContext.AreaType.CIRCLE) {
                throw new IllegalArgumentException("Unsupported legacy search area");
            }
            context = new PlaceSearchContext(
                    null,
                    null,
                    null,
                    List.of(),
                    new PlaceSearchRequest.SearchArea(
                            PlaceSearchRequest.AreaType.CIRCLE,
                            new PlaceSearchRequest.Coordinate(area.center().lat(), area.center().lon()),
                            area.radiusMeters()
                    )
            );
            contextOrigin = Origin.LEGACY_PLAN_AREA;
        }
        if (context == null) context = new PlaceSearchContext(null, null, null, List.of(), null);
        Map<String, Origin> provenance = new LinkedHashMap<>();
        String region = merge("region", text(arguments, "region"), context.region(), contextOrigin, provenance);
        String city = merge("city", text(arguments, "city"), context.city(), contextOrigin, provenance);
        String category = merge("category", text(arguments, "category"), context.category(), contextOrigin, provenance);
        var toolArea = area(arguments.get("area"));
        var effectiveArea = merge("area", toolArea, context.area(), contextOrigin, provenance);
        var excluded = exclusions(arguments.get("exclude_place_ids"));
        var effectiveExclusions = Stream.concat(excluded.stream(), context.excludePlaceIds().stream()).distinct().toList();
        provenance.put("excludePlaceIds", !excluded.isEmpty() && !context.excludePlaceIds().isEmpty() ? Origin.UNION
                : !excluded.isEmpty() ? Origin.TOOL_ARGUMENT : !context.excludePlaceIds().isEmpty() ? contextOrigin : Origin.UNSPECIFIED);
        return new Resolved(
                new PlaceSearchRequest(
                        arguments.get("query").textValue(),
                        region,
                        city,
                        category,
                        effectiveExclusions,
                        effectiveArea,
                        SearchPlacesContract.resultLimit(arguments),
                        RankingMode.RERANKED
                ),
                Map.copyOf(provenance)
        );
    }

    private static String text(JsonNode arguments, String field) {
        JsonNode value = arguments.get(field);
        if (value == null || value.isNull()) return null;
        return value.textValue();
    }

    private PlaceSearchRequest.SearchArea area(JsonNode value) {
        if (value == null || value.isNull()) return null;
        return new PlaceSearchRequest.SearchArea(
                PlaceSearchRequest.AreaType.CIRCLE,
                new PlaceSearchRequest.Coordinate(
                        value.path("center").path("lat").doubleValue(),
                        value.path("center").path("lon").doubleValue()
                ),
                value.path("radius_meters").intValue()
        );
    }

    private static List<Long> exclusions(JsonNode value) {
        if (value == null || value.isNull()) return List.of();
        return java.util.stream.StreamSupport.stream(value.spliterator(), false).map(JsonNode::longValue).toList();
    }

    private static <T> T merge(
            String field,
            T tool,
            T context,
            Origin contextOrigin,
            Map<String, Origin> provenance
    ) {
        if (tool != null && context != null && !Objects.equals(tool, context)) {
            throw new IllegalArgumentException("SEARCH_SCOPE_CONFLICT: " + field);
        }
        provenance.put(field, tool != null ? Origin.TOOL_ARGUMENT : context != null ? contextOrigin : Origin.UNSPECIFIED);
        return tool == null ? context : tool;
    }
}
