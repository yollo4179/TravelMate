package com.yollo.TravelMate.domain.conversation.tool;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.place.data.response.PlaceSearchResponseDto;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class SearchPlacesTool implements ConversationTool {
    private final PlaceSemanticSearchService searches;
    private final PlaceSearchCriteriaResolver criteriaResolver;
    private final ContextPlanPromptFactory prompts;
    private final ObjectMapper mapper;

    @Override
    public LlmTurn.ToolDefinition definition() {
        return new LlmTurn.ToolDefinition(
                Name.SEARCH_PLACES.wireName(),
                "계획 없이 장소와 원문 근거를 검색한다. query는 반드시 직접 작성한다. 선택 필터는 생략할 수 있으며 searchContext를 상속한다. exclude_place_ids는 snake_case다. limit 생략 시 10. 명시 필터와 context가 충돌하면 거부한다.",
                SearchPlacesContract.parameters(),
                LlmTurn.SchemaMode.OPTIONAL_FIELDS
        );
    }

    @Override
    public Result execute(Invocation invocation) {
        var resolved = criteriaResolver.resolve(invocation.request(), invocation.arguments());
        var results = searches.search(resolved.criteria());
        var prepared = prompts.assemble(results.stream().map(result -> result.place()).toList(), results);
        ObjectNode grounded = mapper.createObjectNode().put("searchContractVersion", "place-search-v2");
        grounded.set("searchCriteria", mapper.valueToTree(resolved.criteria()));
        grounded.set("filterProvenance", mapper.valueToTree(resolved.provenance()));
        grounded.set("candidates", mapper.valueToTree(prepared.candidates()));
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
