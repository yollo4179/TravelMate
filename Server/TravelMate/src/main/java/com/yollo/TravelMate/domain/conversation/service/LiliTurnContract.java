package com.yollo.TravelMate.domain.conversation.service;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.ConversationAnswerKind;
import com.yollo.TravelMate.domain.conversation.data.ConversationIntent;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import com.yollo.TravelMate.domain.conversation.tool.ToolSchemas;

/**
 * Strict schemas for LiLi's turns. Property order is generation order, so decisions come before the line
 * that has to agree with them, and citations come before the cuts that rely on them.
 */
public final class LiliTurnContract {
    public static final String ROUTER_NAME = "lili_router_v1";
    public static final String REPLY_NAME = "lili_reply_v1";
    public static final String RECOMMENDATION_NAME = "recommendation_answer_v1";
    public static final int MAX_CHOICES = 3;
    private static final int MAX_QUERY_LENGTH = 300;
    private static final int MAX_CHOICE_LENGTH = 40;
    private static final JsonNodeFactory JSON = JsonNodeFactory.instance;

    private LiliTurnContract() {}

    public static JsonNode routerSchema() {
        var properties = new LinkedHashMap<String, JsonNode>();
        properties.put("branch", enumeration(Arrays.asList(LiliBranch.values())));
        properties.put("intent", enumeration(ConversationIntent.finalValues()));
        properties.put("search_query", ToolSchemas.nullable(ToolSchemas.text(MAX_QUERY_LENGTH)));
        properties.putAll(reply());
        return ToolSchemas.object(properties);
    }

    public static JsonNode replySchema() {
        var properties = new LinkedHashMap<String, JsonNode>();
        properties.put("intent", enumeration(ConversationIntent.finalValues()));
        properties.putAll(reply());
        return ToolSchemas.object(properties);
    }

    public static JsonNode recommendationSchema() {
        var cut = new LinkedHashMap<String, JsonNode>();
        cut.put("text", ToolSchemas.text(DialogueCut.MAX_TEXT_LENGTH));
        cut.put("emotion", enumeration(Arrays.asList(CharacterEmotion.values())));
        ObjectNode dialogue = JSON.objectNode().put("type", "array")
                .put("minItems", DialogueCut.MIN_RESULT_CUTS).put("maxItems", DialogueCut.MAX_RESULT_CUTS);
        dialogue.set("items", ToolSchemas.object(cut));
        var properties = new LinkedHashMap<String, JsonNode>();
        properties.put("intent", enumeration(ConversationIntent.finalValues()));
        properties.put("answerKind", enumeration(Arrays.asList(ConversationAnswerKind.values())));
        properties.put("citations", ConversationAnswerContract.schema().path("properties").path("citations").deepCopy());
        properties.put("dialogue", dialogue);
        return ToolSchemas.object(properties);
    }

    private static Map<String, JsonNode> reply() {
        var properties = new LinkedHashMap<String, JsonNode>();
        properties.put("emotion", enumeration(Arrays.asList(CharacterEmotion.values())));
        properties.put("message", ToolSchemas.text(DialogueCut.MAX_TEXT_LENGTH));
        ObjectNode choices = JSON.objectNode().put("type", "array").put("maxItems", MAX_CHOICES);
        choices.set("items", ToolSchemas.text(MAX_CHOICE_LENGTH));
        properties.put("choices", choices);
        return properties;
    }

    private static ObjectNode enumeration(List<? extends Enum<?>> values) {
        ObjectNode node = JSON.objectNode().put("type", "string");
        var allowed = node.putArray("enum");
        values.forEach(value -> allowed.add(value.name()));
        return node;
    }
}
