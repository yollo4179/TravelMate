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
                "계획 없이 장소와 원문 근거를 검색한다. 명시한 지역·도시·제외 ID·반경은 searchContext와 함께 적용한다. 분위기·시설·조건·장소 관계를 함께 찾을 수 있다.",
                ToolSchemas.object(Map.of(
                        "query", ToolSchemas.text(2000),
                        "limit", ToolSchemas.integer(1, 20),
                        "region", ToolSchemas.nullable(ToolSchemas.text(200)),
                        "city", ToolSchemas.nullable(ToolSchemas.text(200)),
                        "category", ToolSchemas.nullable(ToolSchemas.text(200)),
                        "exclude_place_ids", mapper.createObjectNode().put("type", "array").put("uniqueItems", true).set("items", ToolSchemas.integer(1, Long.MAX_VALUE)),
                        "area", ToolSchemas.nullable(ToolSchemas.object(Map.of(
                                "type", mapper.createObjectNode().put("type", "string").set("enum", mapper.createArrayNode().add("CIRCLE")),
                                "center", ToolSchemas.object(Map.of(
                                        "lat", ToolSchemas.number(-90, 90),
                                        "lon", ToolSchemas.number(-180, 180))),
                                "radius_meters", ToolSchemas.integer(500, 10000))))))
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
