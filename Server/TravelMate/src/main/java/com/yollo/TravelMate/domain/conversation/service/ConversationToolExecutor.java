package com.yollo.TravelMate.domain.conversation.service;

import java.util.Map;
import java.util.TreeMap;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ToolStatus;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
@RequiredArgsConstructor
public class ConversationToolExecutor {
    private final ConversationToolRegistry registry;
    private final ObjectMapper mapper;

    public record Executed(ConversationTool.Result result, ToolStatus status) {}
    private enum ErrorCode { INVALID_TOOL_CALL, TOOL_FAILED }

    public Executed execute(
            LlmTurn.ToolCall call,
            ConversationTool.Invocation invocation,
            Map<String, ConversationTool.Result> cache
    ) {
        try {
            var tool = registry.resolve(call.name());
            if (call.arguments() == null || call.arguments().length() > 16384) {
                throw new IllegalArgumentException("도구 인자가 비어 있거나 너무 깁니다.");
            }
            JsonNode arguments = mapper.reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(call.arguments());
            if (arguments == null || !arguments.isObject()) throw new IllegalArgumentException("도구 인자는 JSON 객체여야 합니다.");
            String signature = call.name() + ":" + canonical(arguments);
            if (cache.containsKey(signature)) return new Executed(cache.get(signature), ToolStatus.CACHED);
            var scoped = ConversationTool.Invocation.builder()
                    .userUid(invocation.userUid()).turnKey(invocation.turnKey())
                    .request(invocation.request()).arguments(arguments).build();
            ConversationTool.Result result;
            try {
                result = tool.execute(scoped);
            } catch (ResponseStatusException exception) {
                result = error(ErrorCode.TOOL_FAILED, exception.getReason());
            } catch (IllegalArgumentException exception) {
                result = error(ErrorCode.INVALID_TOOL_CALL, exception.getMessage());
            } catch (RuntimeException exception) {
                result = error(ErrorCode.TOOL_FAILED, "도구 실행 결과를 확인하지 못했습니다.");
            }
            cache.put(signature, result);
            return new Executed(result, result.type() == ResultType.ERROR ? ToolStatus.FAILED : ToolStatus.SUCCEEDED);
        } catch (Exception exception) {
            return new Executed(error(ErrorCode.INVALID_TOOL_CALL, "등록된 도구 이름과 올바른 JSON 인자가 필요합니다."), ToolStatus.FAILED);
        }
    }

    private ConversationTool.Result error(ErrorCode code, String message) {
        var receipt = mapper.createObjectNode().put("code", code.name()).put("message", message);
        return ConversationTool.Result.builder().type(ResultType.ERROR).publicData(receipt).modelData(receipt).build();
    }

    private JsonNode canonical(JsonNode argument) {
        if (argument.isObject()) {
            Map<String, JsonNode> fields = new TreeMap<>();
            argument.properties().forEach(field -> fields.put(field.getKey(), canonical(field.getValue())));
            ObjectNode sorted = mapper.createObjectNode();
            fields.forEach(sorted::set);
            return sorted;
        }
        if (argument.isArray()) {
            var sorted = mapper.createArrayNode();
            argument.forEach(value -> sorted.add(canonical(value)));
            return sorted;
        }
        return argument;
    }
}
