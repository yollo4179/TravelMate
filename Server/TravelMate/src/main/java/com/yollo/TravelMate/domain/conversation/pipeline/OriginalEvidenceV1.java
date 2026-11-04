package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.place.data.response.PlaceSearchResponseDto;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class OriginalEvidenceV1 implements EvidenceModule {
    private final ContextPlanPromptFactory prompts;
    private final ObjectMapper mapper;

    @Override
    public boolean supports(Version version) {
        return version == Version.ORIGINAL_V1;
    }

    @Override
    public ConversationTool.Result execute(SearchModule.Batch input, ConversationModuleConfig config) {
        var results = input.results();
        var prepared = prompts.assemble(results.stream().map(result -> result.place()).toList(), results);
        ObjectNode grounded = mapper.createObjectNode().put("searchContractVersion", "place-search-v2");
        grounded.set("searchCriteria", mapper.valueToTree(input.resolved().criteria()));
        grounded.set("filterProvenance", mapper.valueToTree(input.resolved().provenance()));
        grounded.set("candidates", mapper.valueToTree(prepared.candidates()));
        String prefix = UUID.randomUUID() + ":";
        Map<String, CitationSource> sources = new LinkedHashMap<>();
        prepared.sources().forEach((evidenceId, source) -> sources.put(prefix + evidenceId, source));
        grounded.path("candidates").forEach(candidate -> candidate.path("selectedEvidence").forEach(evidence ->
                ((ObjectNode) evidence).put("evidenceId", prefix + evidence.path("evidenceId").textValue())));
        return ConversationTool.Result.builder()
                .type(ResultType.PLACES)
                .publicData(mapper.valueToTree(results.stream().map(PlaceSearchResponseDto::from).toList()))
                .modelData(grounded)
                .sources(sources)
                .build();
    }
}
