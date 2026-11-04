package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** The preview line returns now; the search and the grounded explanation run as a recommendation job. */
@Component
@RequiredArgsConstructor
public class LiliSearchHandler implements LiliBranchHandler {
    private final RecommendationJobService recommendations;
    private final LiliActions actions;
    private final ConversationAnswerRenderer renderer;
    private final ObjectMapper mapper;

    @Override
    public boolean supports(LiliBranch branch) {
        return branch == LiliBranch.SEARCH_PLACES;
    }

    @Override
    public ConversationResponse execute(Input input) {
        var turn = input.turn();
        var decision = input.decision();
        long started = System.nanoTime();
        var job = recommendations.submit(turn.userUid(), turn.turnKey(), turn.request(), decision.searchQuery());
        var queued = actions.queued(
                ConversationTool.Name.SEARCH_PLACES,
                mapper.createObjectNode().put("query", decision.searchQuery()),
                job,
                started
        );
        return renderer.dialogue(
                job,
                decision.intent(),
                List.of(),
                List.of(decision.cut()),
                List.of(),
                Termination.COMPLETED,
                1,
                List.of(queued.observation())
        );
    }
}
