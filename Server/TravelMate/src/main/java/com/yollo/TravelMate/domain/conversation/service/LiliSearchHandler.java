package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Map;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * The preview line returns now; the search and the grounded explanation run as a recommendation job.
 * Places LiLi excluded by position are mapped onto the list the app displayed and merged into the app's exclusions.
 */
@Component
@RequiredArgsConstructor
public class LiliSearchHandler implements LiliBranchHandler {
    private static final int FOLLOW_UP_TURNS = 2;
    private static final Map<DisplayedPositions.Status, LiliServerCode> UNRESOLVED = Map.of(
            DisplayedPositions.Status.NO_DISPLAYED_RESULT, LiliServerCode.DISPLAYED_RESULT_MISSING,
            DisplayedPositions.Status.POSITION_OUT_OF_RANGE, LiliServerCode.EXCLUDE_POSITION_OUT_OF_RANGE
    );
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
        var displayed = turn.request().displayedResult();
        var exclusion = DisplayedPositions.resolve(displayed, decision.excludePositions());
        record(exclusion, displayed == null ? null : displayed.resultId().toString());
        if (!exclusion.usable()) return askWhichPlace(input, UNRESOLVED.get(exclusion.status()));
        long started = System.nanoTime();
        var request = turn.request().withExcludedPlaces(exclusion.placeIds());
        var job = recommendations.submit(turn.userUid(), turn.turnKey(), request, decision.searchQuery());
        var arguments = mapper.createObjectNode().put("query", decision.searchQuery());
        if (!exclusion.placeIds().isEmpty()) exclusion.placeIds().forEach(arguments.putArray("exclude_place_ids")::add);
        var queued = actions.queued(ConversationTool.Name.SEARCH_PLACES, arguments, job, started);
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

    private void record(DisplayedPositions.Resolution exclusion, String resultId) {
        var event = mapper.createObjectNode().put("status", exclusion.status().name()).put("resultId", resultId);
        var positions = event.putArray("positions");
        exclusion.positions().forEach(positions::add);
        var placeIds = event.putArray("placeIds");
        exclusion.placeIds().forEach(placeIds::add);
        ObservationContext.record(ObservationContext.Event.EXCLUSION, event);
    }

    private ConversationResponse askWhichPlace(Input input, LiliServerCode code) {
        return actions.followUp(input.turn(), code, null)
                .map(reply -> renderer.dialogue(null, reply.intent(), List.of(), List.of(reply.cut()),
                        reply.choices(), Termination.COMPLETED, FOLLOW_UP_TURNS, List.of()))
                .orElseGet(() -> renderer.render(null, null, Termination.INVALID_RESPONSE, FOLLOW_UP_TURNS, List.of()));
    }
}
