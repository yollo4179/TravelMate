package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
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
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class ConversationAnswerRenderer {
    private static final Map<ResultType, Function<JsonNode, String>> RECEIPT_MESSAGES = Map.of(
            ResultType.PLACES, places -> places.isEmpty() ? "검색 조건에 맞는 장소가 없습니다." : "장소 검색 결과 " + places.size() + "개를 확인했습니다.",
            ResultType.PLANNING_JOB, ConversationAnswerRenderer::jobMessage,
            ResultType.DRAFT, draft -> "서버에서 확인한 일정 초안입니다. 확정 여부와 세부 내용은 반환된 상태와 데이터를 확인해 주세요.",
            ResultType.TEXT, result -> "도구 실행 결과를 확인했습니다.",
            ResultType.ERROR, error -> "도구 실행을 완료하지 못했습니다. 반환된 실패 상태와 사유를 확인해 주세요."
    );
    private final ObjectMapper mapper;
    public enum AnswerKind { PLACE_GUIDANCE, CONVERSATION, CLARIFICATION }

    public record Answer(String message, List<Citation> citations, AnswerKind answerKind) {
        public Answer {
            // Older preserved answers have no kind; absence must not discard verified place data.
            answerKind = answerKind == null ? AnswerKind.PLACE_GUIDANCE : answerKind;
        }

        public Answer(String message, List<Citation> citations) {
            this(message, citations, AnswerKind.PLACE_GUIDANCE);
        }
    }

    public Answer parse(String content, Map<String, CitationSource> sources) throws Exception {
        JsonNode parsed = mapper.reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(content);
        if (parsed == null) throw new IllegalArgumentException("최종 설명이 없습니다.");
        ToolSchemas.requireFields(parsed, parsed.has("answerKind")
                ? Set.of("message", "citations", "answerKind") : Set.of("message", "citations"));
        if (parsed.has("answerKind") && !parsed.get("answerKind").isTextual()) {
            throw new IllegalArgumentException("최종 설명의 종류가 올바르지 않습니다.");
        }
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
        return render(
                primary,
                answer,
                termination,
                modelTurns,
                observations,
                answer == null ? MessageSource.SERVER_FALLBACK : MessageSource.LLM
        );
    }

    public ConversationResponse receipt(
            ConversationTool.Result primary,
            Termination termination,
            int modelTurns,
            List<ToolObservation> observations
    ) {
        String message = termination == Termination.TOOL_FAILED
                ? "도구 실행을 완료하지 못했습니다. 반환된 실패 상태와 사유를 확인해 주세요."
                : RECEIPT_MESSAGES.get(primary.type()).apply(primary.publicData());
        return render(
                primary,
                new Answer(message, List.of()),
                termination,
                modelTurns,
                observations,
                MessageSource.SERVER_RECEIPT
        );
    }

    private ConversationResponse render(
            ConversationTool.Result primary,
            Answer answer,
            Termination termination,
            int modelTurns,
            List<ToolObservation> observations,
            MessageSource messageSource
    ) {
        ResultType type = primary == null
                ? (termination == Termination.COMPLETED ? ResultType.TEXT : ResultType.ERROR) : primary.type();
        JsonNode publicData = primary == null ? mapper.nullNode() : primary.publicData();
        String message = answer == null ? "설명을 완료하지 못했습니다. 확인된 서버 결과와 작업 상태를 확인해 주세요." : answer.message();
        List<Citation> citations = answer == null ? List.of() : answer.citations();
        if (termination == Termination.BUDGET_REJECTED || termination == Termination.COUNT_UNAVAILABLE) {
            message = "토큰 예산이 확인되지 않았거나 한도를 초과해 다음 모델 호출을 중단했습니다.";
        }
        if (type == ResultType.PLANNING_JOB) {
            // 접수 기록을 생성 완료로 바꾸는 자유문장은 현재 상태 영수증을 대신할 수 없다.
            message = jobMessage(publicData);
            if (termination == Termination.TOOL_FAILED) message += " 일부 도구 실행에 실패했습니다. 도구별 실패 상태와 사유를 확인해 주세요.";
            citations = List.of();
            messageSource = MessageSource.SERVER_RECEIPT;
        }
        String primaryId = null;
        for (int index = observations.size() - 1; index >= 0; index--) {
            var observation = observations.get(index);
            if (observation.type() == type && java.util.Objects.equals(observation.publicData(), publicData)) {
                primaryId = observation.resultId();
                break;
            }
        }
        var context = ObservationContext.capture();
        return ConversationResponse.builder().type(type).data(publicData).message(message).citations(citations)
                .termination(termination).modelTurns(modelTurns).toolResults(List.copyOf(observations))
                .requestId(context == null ? null : context.requestId()).turnId(context == null ? null : context.turnId())
                .conversationId(context == null ? null : context.conversationId()).primaryResultId(primaryId)
                .messageSource(messageSource).build();
    }

    private static String jobMessage(JsonNode receipt) {
        var status = com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus.valueOf(receipt.path("status").asText());
        return switch (status) {
            case QUEUED -> "초안 생성 요청을 접수했습니다. 아직 초안이 완성되지 않았습니다.";
            case RUNNING -> "초안을 생성하고 있습니다. 아직 완성되지 않았습니다.";
            case FAILED -> "초안 생성에 실패했습니다. 작업 기록의 실패 사유를 확인해 주세요.";
            case SUCCEEDED -> "생성 작업은 완료됐지만 초안 데이터는 이 응답에서 확인되지 않았습니다.";
        };
    }
}
