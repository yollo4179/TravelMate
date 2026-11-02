package com.yollo.TravelMate.domain.conversation.tool;

import java.util.Map;
import java.util.Set;
import java.util.UUID;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class GetPlanningJobTool implements ConversationTool {
    private final ContextPlanningService planning;
    private final PlanningToolResults results;

    @Override
    public LlmTurn.ToolDefinition definition() {
        return new LlmTurn.ToolDefinition(
                Name.GET_PLANNING_JOB.wireName(),
                "본인 생성 작업의 현재 상태를 한 번 조회한다. 진행 중이면 응답을 끝내고 다음 요청에서 확인한다.",
                ToolSchemas.object(Map.of("job_id", ToolSchemas.text(36)))
        );
    }

    @Override
    public Result execute(Invocation invocation) {
        ToolSchemas.requireFields(invocation.arguments(), Set.of("job_id"));
        var jobId = invocation.arguments().get("job_id");
        if (!jobId.isTextual() || jobId.textValue().length() != 36) {
            throw new IllegalArgumentException("올바른 작업 ID가 필요합니다.");
        }
        return results.fromJob(planning.job(UUID.fromString(jobId.textValue()), invocation.userUid()), invocation.userUid());
    }
}
