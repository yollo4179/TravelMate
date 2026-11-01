package com.yollo.TravelMate.domain.plan.validator;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class ContextPlanResultValidator {
    private final ObjectMapper objectMapper;

    public GeneratedPlan parse(String output) {
        if (output == null || output.isBlank()) {
            throw new IllegalStateException("AI가 빈 결과를 반환했습니다.");
        }
        try {
            return objectMapper.readValue(output, GeneratedPlan.class);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("AI 응답이 일정 JSON 형식과 일치하지 않습니다.", exception);
        }
    }
}
