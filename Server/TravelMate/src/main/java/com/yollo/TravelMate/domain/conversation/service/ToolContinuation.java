package com.yollo.TravelMate.domain.conversation.service;

import java.util.Set;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.tool.ToolSchemas;

public enum ToolContinuation {
    RETURN_RESULT,
    REASSESS;

    public static ToolContinuation parse(String content, ObjectMapper mapper) throws Exception {
        if (content == null || content.isBlank()) return RETURN_RESULT;
        if (content.length() > 1024) throw new IllegalArgumentException("도구 후속 판단 지시가 너무 깁니다.");
        var control = mapper.reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(content);
        if (control == null || !control.isObject()) throw new IllegalArgumentException("도구 후속 판단 지시는 JSON 객체여야 합니다.");
        ToolSchemas.requireFields(control, Set.of("afterTool"));
        if (!control.get("afterTool").isTextual()) throw new IllegalArgumentException("후속 판단 종류가 올바르지 않습니다.");
        return valueOf(control.get("afterTool").textValue());
    }
}
