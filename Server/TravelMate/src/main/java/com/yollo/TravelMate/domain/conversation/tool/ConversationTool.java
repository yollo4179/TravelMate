package com.yollo.TravelMate.domain.conversation.tool;

import java.util.Map;
import java.util.UUID;
import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource;
import lombok.Builder;

public interface ConversationTool {
    LlmTurn.ToolDefinition definition();

    default boolean supports(String name) {
        return definition().name().equals(name);
    }

    Result execute(Invocation invocation);

    enum Name {
        SEARCH_PLACES("search_places"),
        GENERATE_PLAN("generate_plan"),
        GET_PLANNING_JOB("get_planning_job");

        private final String wireName;
        Name(String wireName) { this.wireName = wireName; }
        public String wireName() { return wireName; }
    }

    @Builder
    record Invocation(
            String userUid,
            UUID turnKey,
            ConversationRequest request,
            JsonNode arguments
    ) {}

    @Builder
    record Result(
            ResultType type,
            JsonNode publicData,
            JsonNode modelData,
            Map<String, CitationSource> sources
    ) {
        public Result {
            sources = sources == null ? Map.of() : Map.copyOf(sources);
        }
    }
}
