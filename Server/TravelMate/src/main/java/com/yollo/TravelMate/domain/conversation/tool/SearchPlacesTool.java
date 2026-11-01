package com.yollo.TravelMate.domain.conversation.tool;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.place.data.response.PlaceSearchResponseDto;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class SearchPlacesTool implements ConversationTool {
    private final ContextPlanningService planning;
    private final ContextPlanPromptFactory prompts;
    private final ObjectMapper mapper;

    @Override
    public LlmTurn.ToolDefinition definition() {
        return new LlmTurn.ToolDefinition(
                Name.SEARCH_PLACES.wireName(),
                "서버 여행 범위에서 장소와 원문 근거를 검색한다. 분위기·시설·조건·장소 관계를 함께 찾을 수 있다.",
                ToolSchemas.object(Map.of("query", ToolSchemas.text(2000), "limit", ToolSchemas.integer(1, 20)))
        );
    }

    @Override
    public Result execute(Invocation invocation) {
        ToolSchemas.requireFields(invocation.arguments(), Set.of("query", "limit"));
        var query = invocation.arguments().get("query");
        var limit = invocation.arguments().get("limit");
        if (!query.isTextual() || query.textValue().isBlank() || query.textValue().length() > 2000
                || !limit.isIntegralNumber() || !limit.canConvertToInt() || limit.intValue() < 1 || limit.intValue() > 20) {
            throw new IllegalArgumentException("검색 문장과 1~20개 결과 수가 필요합니다.");
        }
        var request = invocation.request().planningRequest();
        if (request == null) throw new IllegalArgumentException("검색 범위가 포함된 여행 조건이 필요합니다.");
        var results = planning.search(request.context(), query.textValue(), limit.intValue());
        var prepared = prompts.prepare(request, results.stream().map(result -> result.place()).toList(), results);
        ObjectNode grounded = mapper.valueToTree(prepared.groundedRequest());
        String prefix = UUID.randomUUID() + ":";
        Map<String, CitationSource> sources = new LinkedHashMap<>();
        prepared.sources().forEach((evidenceId, source) -> sources.put(prefix + evidenceId, source));
        grounded.path("candidates").forEach(candidate -> candidate.path("selectedEvidence").forEach(evidence ->
                ((ObjectNode) evidence).put("evidenceId", prefix + evidence.path("evidenceId").textValue())));
        return Result.builder()
                .type(ResultType.PLACES)
                .publicData(mapper.valueToTree(results.stream().map(PlaceSearchResponseDto::from).toList()))
                .modelData(grounded)
                .sources(sources)
                .build();
    }
}
