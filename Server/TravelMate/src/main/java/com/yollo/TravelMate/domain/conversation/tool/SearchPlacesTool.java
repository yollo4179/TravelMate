package com.yollo.TravelMate.domain.conversation.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationSearchPipeline;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class SearchPlacesTool implements ConversationTool {
    private final ConversationSearchPipeline pipeline;
    private final PlaceSearchCriteriaResolver criteriaResolver;

    @Autowired
    public SearchPlacesTool(
            ConversationSearchPipeline pipeline,
            PlaceSearchCriteriaResolver criteriaResolver
    ) {
        this.pipeline = pipeline;
        this.criteriaResolver = criteriaResolver;
    }

    public SearchPlacesTool(
            PlaceSemanticSearchService searches,
            PlaceSearchCriteriaResolver criteriaResolver,
            ContextPlanPromptFactory prompts,
            ObjectMapper mapper
    ) {
        this(ConversationSearchPipeline.defaults(searches, prompts, mapper), criteriaResolver);
    }

    @Override
    public LlmTurn.ToolDefinition definition() {
        return new LlmTurn.ToolDefinition(
                Name.SEARCH_PLACES.wireName(),
                "계획 없이 장소와 원문 근거를 검색한다. query는 반드시 직접 작성하며 세부 장소 유형·분위기·관계 조건을 유지한다. category는 DB 대분류 enum만 사용하고 확정할 수 없으면 생략 또는 null로 둔다. arguments에는 스키마 필드만 직접 넣고 searchContext 객체는 넣지 않는다. 선택 필터를 생략하면 서버가 사용자 요청의 searchContext를 상속한다. exclude_place_ids는 snake_case다. limit 생략 시 10. 명시 필터와 context가 충돌하거나 허용되지 않는 category이면 거부하며 자동 보정하지 않는다.",
                SearchPlacesContract.parameters(),
                LlmTurn.SchemaMode.OPTIONAL_FIELDS
        );
    }

    @Override
    public Result execute(Invocation invocation) {
        var resolved = criteriaResolver.resolve(invocation.request(), invocation.arguments());
        return pipeline.execute(resolved);
    }
}
