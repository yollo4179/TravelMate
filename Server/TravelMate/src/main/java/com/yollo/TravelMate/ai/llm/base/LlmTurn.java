package com.yollo.TravelMate.ai.llm.base;

import java.util.List;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.Builder;

@Builder
public record LlmTurn(
        String content,
        List<ToolCall> toolCalls,
        List<JsonNode> continuation
) {
    public LlmTurn {
        content = content == null ? "" : content;
        toolCalls = toolCalls == null ? List.of() : List.copyOf(toolCalls);
        continuation = continuation == null ? List.of() : continuation.stream().<JsonNode>map(JsonNode::deepCopy).toList();
    }

    @Builder
    public record ToolCall(String id, String name, String arguments) {}

    public enum SchemaMode { STRICT, OPTIONAL_FIELDS }

    public record ToolDefinition(String name, String description, JsonNode parameters, SchemaMode schemaMode) {
        public ToolDefinition(String name, String description, JsonNode parameters) {
            this(name, description, parameters, SchemaMode.STRICT);
        }
    }
}
