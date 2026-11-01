package com.yollo.TravelMate.ai.llm.base;

import java.util.List;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.Builder;

@Builder
public record LlmMessage(
        Role role,
        String content,
        List<LlmTurn.ToolCall> toolCalls,
        String toolCallId,
        String toolName,
        List<JsonNode> continuation
) {
    public enum Role { SYSTEM, USER, ASSISTANT, TOOL }

    public LlmMessage {
        toolCalls = toolCalls == null ? List.of() : List.copyOf(toolCalls);
        continuation = continuation == null ? List.of() : continuation.stream().<JsonNode>map(JsonNode::deepCopy).toList();
    }

    public static LlmMessage text(Role role, String content) {
        return builder().role(role).content(content).build();
    }

    public static LlmMessage assistant(LlmTurn turn) {
        return builder().role(Role.ASSISTANT).content(turn.content())
                .toolCalls(turn.toolCalls()).continuation(turn.continuation()).build();
    }

    public static LlmMessage tool(LlmTurn.ToolCall call, String result) {
        return builder().role(Role.TOOL).content(result).toolCallId(call.id()).toolName(call.name()).build();
    }
}
