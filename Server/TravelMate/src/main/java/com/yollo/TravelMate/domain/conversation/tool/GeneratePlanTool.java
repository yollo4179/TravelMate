package com.yollo.TravelMate.domain.conversation.tool;

import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.nio.charset.StandardCharsets;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class GeneratePlanTool implements ConversationTool {
    private final ContextPlanningService planning;
    private final PlanningToolResults results;

    @Override
    public LlmTurn.ToolDefinition definition() {
        return new LlmTurn.ToolDefinition(
                Name.GENERATE_PLAN.wireName(),
                "입력된 여행 조건 그대로 비동기 DRAFT 생성을 요청한다. Job 접수는 초안 완성이 아니다. 확정·최적화 도구가 아니다.",
                ToolSchemas.object(Map.of())
        );
    }

    @Override
    public Result execute(Invocation invocation) {
        ToolSchemas.requireFields(invocation.arguments(), Set.of());
        var request = invocation.request().planningRequest();
        if (request == null) throw new IllegalArgumentException("초안 생성에 필요한 여행 조건을 먼저 입력해야 합니다.");
        UUID key = UUID.nameUUIDFromBytes((invocation.userUid() + ":" + invocation.turnKey() + ":generate_plan")
                .getBytes(StandardCharsets.UTF_8));
        return results.fromJob(planning.generate(invocation.userUid(), key, request), invocation.userUid());
    }
}
