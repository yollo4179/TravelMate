package com.yollo.TravelMate.domain.conversation.tool;

import java.util.Map;
import java.util.Set;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;

public final class SearchPlacesContract {
    private static final JsonNodeFactory JSON = JsonNodeFactory.instance;
    private static final ObjectNode PARAMETERS = parametersSchema();

    private SearchPlacesContract() {}

    public static JsonNode parameters() {
        return PARAMETERS.deepCopy();
    }

    public static void validate(JsonNode arguments) {
        // Query is mandatory even when the user message could be used to guess one.
        if (!arguments.isObject() || !arguments.path("query").isTextual()) {
            throw new IllegalArgumentException("Search query required");
        }
        ToolSchemas.validate(PARAMETERS, arguments);
    }

    public static int resultLimit(JsonNode arguments) {
        return arguments.has("limit") ? arguments.get("limit").intValue()
                : PARAMETERS.path("properties").path("limit").path("default").intValue();
    }

    private static ObjectNode parametersSchema() {
        ObjectNode exclusions = JSON.objectNode().put("type", "array").put("uniqueItems", true);
        exclusions.set("items", ToolSchemas.integer(1, Long.MAX_VALUE));
        ObjectNode optionalExclusions = ToolSchemas.nullable(exclusions);
        optionalExclusions.set("default", JSON.arrayNode());
        optionalExclusions.put("description", "생략 또는 null이면 빈 목록. searchContext의 제외 ID와 합친다.");
        return ToolSchemas.object(Map.of(
                "query", ToolSchemas.text(2000).put("pattern", "\\S").put("description", "필수 검색어. 사용자 질문에 맞춰 직접 작성하며 서버가 대신 채우지 않는다."),
                "limit", ToolSchemas.integer(1, 20).put("default", 10),
                "region", inheritedText(),
                "city", inheritedText(),
                "category", inheritedText(),
                "exclude_place_ids", optionalExclusions,
                "area", ToolSchemas.nullable(ToolSchemas.object(Map.of(
                        "type", JSON.objectNode().put("type", "string").set("enum", JSON.arrayNode().add("CIRCLE")),
                        "center", ToolSchemas.object(Map.of(
                                "lat", ToolSchemas.number(-90, 90),
                                "lon", ToolSchemas.number(-180, 180))),
                        "radius_meters", ToolSchemas.integer(500, 10000))))
                        .put("description", "생략 또는 null이면 searchContext의 area를 사용한다. 둘 다 없으면 반경 제한 없음.")
        ), Set.of("query"));
    }

    private static ObjectNode inheritedText() {
        return ToolSchemas.nullable(ToolSchemas.text(200).put("pattern", "\\S"))
                .put("description", "선택 필터. 생략 또는 null이면 searchContext 값을 사용한다. 둘 다 없으면 제한 없음.");
    }
}
