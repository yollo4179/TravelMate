package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliFixedLines;
import com.yollo.TravelMate.domain.plan.data.internal.PlanFailure;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.service.PlanFailureReaction;
import org.springframework.stereotype.Component;

/** The model call itself failed or the cause is unknown, so LiLi's prepared line is used without calling the model again. */
@Component
public class PreparedLinePlanFailureReaction implements PlanFailureReaction {
    @Override
    public boolean supports(PlanFailure.Reaction reaction) {
        return reaction == PlanFailure.Reaction.FIXED_LINE;
    }

    @Override
    public List<DialogueCut> execute(
            PlanFailure.Classified failure,
            GeneratePlanRequest request
    ) {
        return List.of(LiliFixedLines.line(LiliFixedLines.Line.PLAN_UNAVAILABLE));
    }
}
