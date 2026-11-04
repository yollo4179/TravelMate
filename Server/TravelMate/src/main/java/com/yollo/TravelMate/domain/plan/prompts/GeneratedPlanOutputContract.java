package com.yollo.TravelMate.domain.plan.prompts;

import java.util.Map;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.yollo.TravelMate.domain.conversation.tool.ToolSchemas;

/** Provider formatting complements, and never replaces, the common draft validator. */
public final class GeneratedPlanOutputContract {
    private GeneratedPlanOutputContract() {}
    public static JsonNode schema() {
        var citations = JsonNodeFactory.instance.objectNode().put("type", "array");
        citations.set("items", ToolSchemas.object(Map.of(
                "evidenceId", ToolSchemas.text(500), "sourceId", ToolSchemas.text(500), "quote", ToolSchemas.text(20000))));
        var pins = JsonNodeFactory.instance.objectNode().put("type", "array").put("minItems", 1).put("maxItems", 6);
        pins.set("items", ToolSchemas.object(Map.of(
                "placeId", ToolSchemas.integer(1, Long.MAX_VALUE), "sequence", ToolSchemas.integer(1, 6),
                "activity", ToolSchemas.text(2000), "reason", ToolSchemas.text(4000), "citations", citations)));
        // The draft is presented by LiLi in the same cut format as recommendations.
        var dialogue = com.yollo.TravelMate.domain.conversation.service.LiliTurnContract.recommendationSchema()
                .path("properties").path("dialogue").deepCopy();
        return ToolSchemas.object(Map.of(
                "planTitle", ToolSchemas.text(200),
                "planDescription", ToolSchemas.text(4000),
                "pins", pins,
                "dialogue", dialogue
        ));
    }
}
