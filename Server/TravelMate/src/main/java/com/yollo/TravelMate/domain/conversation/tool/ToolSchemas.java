package com.yollo.TravelMate.domain.conversation.tool;

import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

public final class ToolSchemas {
    private static final ObjectMapper JSON = new ObjectMapper();
    private ToolSchemas() {}

    public static ObjectNode object(Map<String, JsonNode> properties) {
        var schema = JSON.createObjectNode().put("type", "object").put("additionalProperties", false);
        var fields = schema.putObject("properties");
        properties.forEach((name, definition) -> fields.set(name, definition));
        var required = schema.putArray("required");
        properties.keySet().stream().sorted().forEach(required::add);
        return schema;
    }

    public static ObjectNode text(int maximum) {
        return JSON.createObjectNode().put("type", "string").put("minLength", 1).put("maxLength", maximum);
    }

    public static ObjectNode integer(int minimum, int maximum) {
        return JSON.createObjectNode().put("type", "integer").put("minimum", minimum).put("maximum", maximum);
    }

    public static void requireFields(JsonNode arguments, Set<String> required) {
        Set<String> actual = new HashSet<>();
        arguments.fieldNames().forEachRemaining(actual::add);
        if (!arguments.isObject() || !actual.equals(required)) {
            throw new IllegalArgumentException("도구 인자 필드가 정의와 일치하지 않습니다.");
        }
    }
}
