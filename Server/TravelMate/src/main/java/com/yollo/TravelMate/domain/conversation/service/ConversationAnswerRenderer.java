package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Map;
import java.util.Set;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.*;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ToolSchemas;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource;
import com.yollo.TravelMate.domain.plan.validator.PlanEvidenceCitationValidator;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class ConversationAnswerRenderer {
    private final ObjectMapper mapper;
    public record Answer(String message, List<Citation> citations) {}

    public Answer parse(String content, Map<String, CitationSource> sources) throws Exception {
        JsonNode parsed = mapper.reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(content);
        if (parsed == null) throw new IllegalArgumentException("최종 설명이 없습니다.");
        ToolSchemas.requireFields(parsed, Set.of("message", "citations"));
        if (!parsed.get("message").isTextual() || parsed.get("message").asText().isBlank()
                || parsed.get("message").asText().length() > 8000
                || !parsed.get("citations").isArray() || parsed.get("citations").size() > 30) {
            throw new IllegalArgumentException("최종 설명 형식이 올바르지 않습니다.");
        }
        for (var citation : parsed.get("citations")) {
            ToolSchemas.requireFields(citation, Set.of("placeId", "evidenceId", "sourceId", "quote"));
            if (!citation.get("placeId").isIntegralNumber() || !citation.get("placeId").canConvertToLong()
                    || !citation.get("evidenceId").isTextual() || !citation.get("sourceId").isTextual()
                    || !citation.get("quote").isTextual()) {
                throw new IllegalArgumentException("출처 형식이 올바르지 않습니다.");
            }
        }
        var answer = mapper.treeToValue(parsed, Answer.class);
        for (var citation : answer.citations()) {
            PlanEvidenceCitationValidator.validate(
                    citation.placeId(),
                    new GeneratedPlan.SourceCitation(citation.evidenceId(), citation.sourceId(), citation.quote()),
                    sources
            );
        }
        return answer;
    }

    public ConversationResponse render(
            ConversationTool.Result primary,
            Answer answer,
            Termination termination,
            int modelTurns,
            List<ToolObservation> observations
    ) {
        ResultType type = primary == null
                ? (termination == Termination.COMPLETED ? ResultType.TEXT : ResultType.ERROR) : primary.type();
        JsonNode publicData = primary == null ? mapper.nullNode() : primary.publicData();
        String message = answer == null ? "설명을 완료하지 못했습니다. 확인된 서버 결과와 작업 상태를 확인해 주세요." : answer.message();
        List<Citation> citations = answer == null ? List.of() : answer.citations();
        if (type == ResultType.PLANNING_JOB) {
            // 접수 기록을 생성 완료로 바꾸는 자유문장은 현재 상태 영수증을 대신할 수 없다.
            message = jobMessage(publicData);
            citations = List.of();
        }
        return ConversationResponse.builder().type(type).data(publicData).message(message).citations(citations)
                .termination(termination).modelTurns(modelTurns).toolResults(List.copyOf(observations)).build();
    }

    private String jobMessage(JsonNode receipt) {
        var status = com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus.valueOf(receipt.path("status").asText());
        return switch (status) {
            case QUEUED -> "초안 생성 요청을 접수했습니다. 아직 초안이 완성되지 않았습니다.";
            case RUNNING -> "초안을 생성하고 있습니다. 아직 완성되지 않았습니다.";
            case FAILED -> "초안 생성에 실패했습니다. 작업 기록의 실패 사유를 확인해 주세요.";
            case SUCCEEDED -> "생성 작업은 완료됐지만 초안 데이터는 이 응답에서 확인되지 않았습니다.";
        };
    }
}
