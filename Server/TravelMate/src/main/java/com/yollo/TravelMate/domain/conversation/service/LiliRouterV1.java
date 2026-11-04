package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationRoutingModule;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliPrompts;
import com.yollo.TravelMate.domain.conversation.pipeline.ModuleSelection;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * LiLi answers first without place evidence and decides the branch. Search and plans run as jobs afterwards,
 * so the chat line is never delayed by retrieval and unrelated places never reach a plain conversation.
 */
@Component
@RequiredArgsConstructor
public class LiliRouterV1 implements ConversationRoutingModule {
    private final LiliTurns lili;
    private final List<LiliBranchHandler> handlers;
    private final ConversationAnswerRenderer renderer;
    private final ObjectMapper mapper;

    @Override
    public boolean supports(Version version) {
        return version == Version.LILI_ROUTER_V1;
    }

    @Override
    public ConversationResponse execute(Turn turn) {
        var request = turn.request();
        // LiLi gets facts the server can check exactly, not the IDs themselves: she picks a branch and positions,
        // and the server resolves them.
        var input = mapper.createObjectNode().put("message", request.message())
                .put("intentHint", request.intentHint().name())
                .put("planningRequestProvided", request.planningRequest() != null)
                .put("jobIdProvided", PlanningJobReference.single(request.message()).isPresent())
                .put("displayedResultCount", request.displayedResult() == null ? 0 : request.displayedResult().placeIds().size());
        input.set("searchContext", mapper.valueToTree(request.searchContext()));
        long started = System.nanoTime();
        final LlmTurn completion;
        try {
            completion = lili.call(LiliPrompts.Prompt.ROUTER, request, input,
                    LiliTurnContract.ROUTER_NAME, LiliTurnContract.routerSchema());
        } catch (RuntimeException exception) {
            lili.record(LiliTurns.Stage.ROUTER, LiliPrompts.Prompt.ROUTER, null, elapsed(started));
            return renderer.liliFallback(null, RecommendationJobService.termination(exception), 1, List.of());
        }
        lili.record(LiliTurns.Stage.ROUTER, LiliPrompts.Prompt.ROUTER, completion, elapsed(started));
        final LiliTurns.Decision decision;
        try {
            decision = lili.decision(completion.content());
        } catch (Exception exception) {
            return renderer.liliFallback(null, Termination.INVALID_RESPONSE, 1, List.of());
        }
        var handler = ModuleSelection.requireOne(handlers, candidate -> candidate.supports(decision.branch()), "LiLi branch");
        return handler.execute(new LiliBranchHandler.Input(turn, decision));
    }

    private static double elapsed(long started) {
        return (System.nanoTime() - started) / 1_000_000.0;
    }
}
