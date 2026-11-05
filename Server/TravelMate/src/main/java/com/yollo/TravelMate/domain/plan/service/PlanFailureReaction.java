package com.yollo.TravelMate.domain.plan.service;

import java.util.List;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.plan.data.internal.PlanFailure;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;

/**
 * LiLi's reaction to a failed draft job, stored with the job so the user hears it in her voice instead of the server's
 * error text. Exactly one implementation supports each reaction kind.
 */
public interface PlanFailureReaction {
    boolean supports(PlanFailure.Reaction reaction);

    /** Never throws: a reaction that cannot be made falls back to LiLi's prepared line. */
    List<DialogueCut> execute(
            PlanFailure.Classified failure,
            GeneratePlanRequest request
    );
}
