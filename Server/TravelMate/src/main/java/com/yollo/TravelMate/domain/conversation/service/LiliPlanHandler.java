package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** Queues a draft job with LiLi's search query; missing conditions or a rejected job get a follow-up line. */
@Component
@RequiredArgsConstructor
public class LiliPlanHandler implements LiliBranchHandler {
    private final LiliActions actions;
    private final ConversationAnswerRenderer renderer;
    private final ObjectMapper mapper;

    @Override
    public boolean supports(LiliBranch branch) {
        return branch == LiliBranch.GENERATE_PLAN;
    }

    @Override
    public ConversationResponse execute(Input input) {
        var turn = input.turn();
        var decision = input.decision();
        var planning = turn.request().planningRequest();
        if (planning == null) {
            return actions.followUp(turn, LiliServerCode.PLANNING_CONDITIONS_MISSING, null)
                    .map(reply -> renderer.dialogue(null, reply.intent(), List.of(), List.of(reply.cut()),
                            reply.choices(), Termination.COMPLETED, 2, List.of()))
                    .orElseGet(() -> renderer.render(null, null, Termination.INVALID_RESPONSE, 2, List.of()));
        }
        var request = turn.request().withPlanningRequest(planning.withSearchQuery(decision.searchQuery()));
        var executed = actions.run(turn, request, ConversationTool.Name.GENERATE_PLAN, mapper.createObjectNode());
        if (!executed.failed()) {
            return renderer.dialogue(executed.result(), decision.intent(), List.of(), List.of(decision.cut()),
                    List.of(), Termination.COMPLETED, 1, List.of(executed.observation()));
        }
        String reason = executed.result().modelData().path("message").asText(null);
        return actions.followUp(turn, LiliServerCode.PLAN_REQUEST_FAILED, reason)
                .map(reply -> renderer.dialogue(executed.result(), reply.intent(), List.of(), List.of(reply.cut()),
                        reply.choices(), Termination.TOOL_FAILED, 2, List.of(executed.observation())))
                .orElseGet(() -> renderer.receipt(executed.result(), Termination.TOOL_FAILED, 1,
                        List.of(executed.observation())));
    }
}
