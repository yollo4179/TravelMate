package com.yollo.TravelMate.domain.conversation.tool;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Stream;
import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchContext;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService.RankingMode;
import org.springframework.stereotype.Component;

@Component
public class PlaceSearchCriteriaResolver {
    private static final Set<String> FIELDS = Set.of("query", "region", "city", "category", "exclude_place_ids", "area", "limit");
    public enum Origin { TOOL_ARGUMENT, SEARCH_CONTEXT, LEGACY_PLAN_AREA, UNION, UNSPECIFIED }
    public record Resolved(PlaceSearchRequest criteria, Map<String, Origin> provenance) {}

    public Resolved resolve(ConversationRequest request, JsonNode arguments) {
        if (!arguments.isObject() || !arguments.path("query").isTextual()) throw new IllegalArgumentException("Search query required");
        if (arguments.path("query").textValue().isBlank() || arguments.path("query").textValue().length() > 2000) {
            throw new IllegalArgumentException("Invalid search query");
        }
        arguments.fieldNames().forEachRemaining(name -> {
            if (!FIELDS.contains(name)) throw new IllegalArgumentException("Unknown search argument: " + name);
        });
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
        JsonNode limit = arguments.get("limit");
        if (limit != null && (!limit.isIntegralNumber() || !limit.canConvertToInt() || limit.intValue() < 1 || limit.intValue() > 20)) {
            throw new IllegalArgumentException("Invalid search limit");
        }
        return new Resolved(
                new PlaceSearchRequest(
                        arguments.get("query").textValue(),
                        region,
                        city,
                        category,
                        effectiveExclusions,
                        effectiveArea,
                        limit == null ? 10 : limit.intValue(),
                        RankingMode.RERANKED
                ),
                Map.copyOf(provenance)
        );
    }

    private static String text(JsonNode arguments, String field) {
        JsonNode value = arguments.get(field);
        if (value == null || value.isNull()) return null;
        if (!value.isTextual() || value.textValue().isBlank()) throw new IllegalArgumentException("Invalid search filter: " + field);
        return value.textValue();
    }

    private PlaceSearchRequest.SearchArea area(JsonNode value) {
        if (value == null || value.isNull()) return null;
        ToolSchemas.requireFields(value, Set.of("type", "center", "radius_meters"));
        ToolSchemas.requireFields(value.path("center"), Set.of("lat", "lon"));
        if (!"CIRCLE".equals(value.path("type").asText()) || !value.path("radius_meters").isIntegralNumber()
                || !value.path("radius_meters").canConvertToInt() || !value.path("center").path("lat").isNumber()
                || !value.path("center").path("lon").isNumber()) throw new IllegalArgumentException("Invalid search area");
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
        if (!value.isArray()) throw new IllegalArgumentException("Invalid excluded place IDs");
        if (java.util.stream.StreamSupport.stream(value.spliterator(), false).distinct().count() != value.size()) {
            throw new IllegalArgumentException("Duplicate excluded place IDs");
        }
        return java.util.stream.StreamSupport.stream(value.spliterator(), false).map(identifier -> {
            if (!identifier.isIntegralNumber() || !identifier.canConvertToLong() || identifier.longValue() <= 0) {
                throw new IllegalArgumentException("Invalid excluded place ID");
            }
            return identifier.longValue();
        }).toList();
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
