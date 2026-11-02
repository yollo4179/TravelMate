package com.yollo.TravelMate.domain.conversation.tool;

import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.math.BigDecimal;
import java.util.regex.Pattern;
import java.util.stream.StreamSupport;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

public final class ToolSchemas {
    private static final ObjectMapper JSON = new ObjectMapper();
    private ToolSchemas() {}

    public static ObjectNode object(Map<String, JsonNode> properties) {
        return object(properties, properties.keySet());
    }

    public static ObjectNode object(Map<String, JsonNode> properties, Set<String> requiredFields) {
        if (!properties.keySet().containsAll(requiredFields)) throw new IllegalArgumentException("Unknown required field");
        var schema = JSON.createObjectNode().put("type", "object").put("additionalProperties", false);
        var fields = schema.putObject("properties");
        properties.forEach((name, definition) -> fields.set(name, definition));
        var required = schema.putArray("required");
        requiredFields.stream().sorted().forEach(required::add);
        return schema;
    }

    public static void validate(JsonNode schema, JsonNode argument) {
        validate(schema, argument, "$");
    }

    private static void validate(JsonNode schema, JsonNode argument, String path) {
        if (schema.has("anyOf")) {
            boolean accepted = StreamSupport.stream(schema.path("anyOf").spliterator(), false).anyMatch(option -> {
                try {
                    validate(option, argument, path);
                    return true;
                } catch (IllegalArgumentException exception) {
                    return false;
                }
            });
            if (!accepted) throw new IllegalArgumentException("Invalid tool argument: " + path);
            return;
        }
        String type = schema.path("type").asText();
        boolean validType = switch (type) {
            case "null" -> argument.isNull();
            case "object" -> argument.isObject();
            case "array" -> argument.isArray();
            case "string" -> argument.isTextual();
            case "integer" -> argument.isNumber() && argument.canConvertToExactIntegral();
            case "number" -> argument.isNumber() && Double.isFinite(argument.doubleValue());
            default -> throw new IllegalArgumentException("Unsupported tool schema type: " + type);
        };
        if (!validType) throw new IllegalArgumentException("Invalid tool argument type: " + path);
        if (schema.has("enum") && !StreamSupport.stream(schema.path("enum").spliterator(), false).anyMatch(argument::equals)) {
            throw new IllegalArgumentException("Invalid tool argument value: " + path);
        }
        if (argument.isObject()) {
            schema.path("required").forEach(field -> {
                if (!argument.has(field.asText())) throw new IllegalArgumentException("Required tool argument: " + path + "." + field.asText());
            });
            argument.properties().forEach(field -> {
                JsonNode property = schema.path("properties").get(field.getKey());
                if (property == null) throw new IllegalArgumentException("Unknown tool argument: " + path + "." + field.getKey());
                validate(property, field.getValue(), path + "." + field.getKey());
            });
        }
        if (argument.isArray()) {
            if (schema.path("uniqueItems").asBoolean(false)
                    && StreamSupport.stream(argument.spliterator(), false).map(ToolSchemas::canonicalValue).distinct().count() != argument.size()) {
                throw new IllegalArgumentException("Duplicate tool argument: " + path);
            }
            argument.forEach(item -> validate(schema.path("items"), item, path + "[]"));
        }
        if (argument.isTextual()) {
            String text = argument.textValue();
            int length = text.codePointCount(0, text.length());
            if (length < schema.path("minLength").asInt(0) || length > schema.path("maxLength").asInt(Integer.MAX_VALUE)
                    || (schema.has("pattern") && !Pattern.compile(schema.path("pattern").textValue(), Pattern.UNICODE_CHARACTER_CLASS).matcher(text).find())) {
                throw new IllegalArgumentException("Invalid tool argument text: " + path);
            }
        }
        if (argument.isNumber()) {
            BigDecimal number = argument.decimalValue();
            if ((schema.has("minimum") && number.compareTo(schema.path("minimum").decimalValue()) < 0)
                    || (schema.has("maximum") && number.compareTo(schema.path("maximum").decimalValue()) > 0)) {
                throw new IllegalArgumentException("Invalid tool argument range: " + path);
            }
        }
    }

    private static String canonicalValue(JsonNode value) {
        return value.isNumber() ? value.decimalValue().stripTrailingZeros().toPlainString() : value.toString();
    }

    public static ObjectNode text(int maximum) {
        return JSON.createObjectNode().put("type", "string").put("minLength", 1).put("maxLength", maximum);
    }

    public static ObjectNode integer(long minimum, long maximum) {
        return JSON.createObjectNode().put("type", "integer").put("minimum", minimum).put("maximum", maximum);
    }

    public static ObjectNode number(double minimum, double maximum) {
        return JSON.createObjectNode().put("type", "number").put("minimum", minimum).put("maximum", maximum);
    }

    public static ObjectNode nullable(JsonNode definition) {
        var union = JSON.createObjectNode();
        union.putArray("anyOf").add(definition).add(JSON.createObjectNode().put("type", "null"));
        return union;
    }

    public static void requireFields(JsonNode arguments, Set<String> required) {
        Set<String> actual = new HashSet<>();
        arguments.fieldNames().forEachRemaining(actual::add);
        if (!arguments.isObject() || !actual.equals(required)) {
            throw new IllegalArgumentException("도구 인자 필드가 정의와 일치하지 않습니다.");
        }
    }
}
