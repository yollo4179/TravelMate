package com.yollo.TravelMate.domain.conversation.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Arrays;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.ConversationAnswerKind;
import com.yollo.TravelMate.domain.conversation.data.ConversationIntent;
import java.util.Map;
import com.yollo.TravelMate.domain.conversation.tool.ToolSchemas;

public final class ConversationAnswerContract {
    private ConversationAnswerContract() {}

    public static JsonNode schema() {
        var json = JsonNodeFactory.instance;
        ObjectNode kind = json.objectNode().put("type", "string");
        var allowed = kind.putArray("enum");
        Arrays.stream(ConversationAnswerKind.values()).forEach(value -> allowed.add(value.name()));
        ObjectNode intent = json.objectNode().put("type", "string");
        var intents = intent.putArray("enum");
        ConversationIntent.finalValues().forEach(value -> intents.add(value.name()));
        ObjectNode emotion = json.objectNode().put("type", "string");
        var emotions = emotion.putArray("enum");
        Arrays.stream(CharacterEmotion.values()).forEach(value -> emotions.add(value.name()));
        ObjectNode citation = ToolSchemas.object(Map.of(
                "placeId", ToolSchemas.integer(1, Long.MAX_VALUE),
                "evidenceId", ToolSchemas.text(500),
                "sourceId", ToolSchemas.text(500),
                "quote", ToolSchemas.text(20000)
        ));
        ObjectNode citations = json.objectNode().put("type", "array");
        citations.set("items", citation);
        return ToolSchemas.object(Map.of(
                "message", ToolSchemas.text(8000),
                "citations", citations,
                "answerKind", kind,
                "emotion", emotion,
                "intent", intent
        ));
    }
}
