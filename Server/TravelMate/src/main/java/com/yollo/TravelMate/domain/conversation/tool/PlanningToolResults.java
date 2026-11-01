package com.yollo.TravelMate.domain.conversation.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class PlanningToolResults {
    private final ContextPlanningService planning;
    private final ObjectMapper mapper;

    public ConversationTool.Result fromJob(PlanningResponse.Job job, String userUid) {
        if (job == null || job.status() == null || job.jobId() == null) {
            throw new IllegalStateException("생성 작업 접수 결과를 확인할 수 없습니다.");
        }
        if (job.status() != PlanningResponse.JobStatus.SUCCEEDED) {
            var receipt = mapper.valueToTree(job);
            return ConversationTool.Result.builder()
                    .type(ResultType.PLANNING_JOB).publicData(receipt).modelData(receipt).build();
        }
        if (job.planId() == null) throw new IllegalStateException("완료 작업에 초안 ID가 없습니다.");
        var draft = planning.plan(job.planId(), userUid);
        if (draft == null || !job.planId().equals(draft.planId())) {
            throw new IllegalStateException("완성된 초안을 조회하지 못했습니다.");
        }
        var stored = mapper.valueToTree(draft);
        return ConversationTool.Result.builder().type(ResultType.DRAFT).publicData(stored).modelData(stored).build();
    }
}
