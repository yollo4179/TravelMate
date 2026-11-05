package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Objects;
import java.util.stream.Stream;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliFixedLines;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliPrompts;
import com.yollo.TravelMate.domain.plan.data.internal.PlanFailure;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.service.PlanFailureReaction;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * LiLi reacts to a failure whose cause the server verified (nothing in the area, a rule refused the draft), so the
 * user hears what was searched and what to change rather than the server's error text.
 */
@Component
@RequiredArgsConstructor
public class LiliPlanFailureReaction implements PlanFailureReaction {
    private static final String TRIP_REQUEST = "일정 초안을 만들어 달라는 요청";

    private final LiliTurns lili;
    private final ObjectMapper mapper;

    @Override
    public boolean supports(PlanFailure.Reaction reaction) {
        return reaction == PlanFailure.Reaction.LILI;
    }

    @Override
    public List<DialogueCut> execute(
            PlanFailure.Classified failure,
            GeneratePlanRequest request
    ) {
        String asked = askedFor(request);
        var input = mapper.createObjectNode().put("message", asked);
        input.putObject("serverResult")
                .put("situation", failure.kind().situation())
                .put("reason", failure.userMessage())
                .put("askUser", false);
        long started = System.nanoTime();
        try {
            var completion = lili.call(LiliPrompts.Prompt.FOLLOWUP, new ConversationRequest(asked, null, List.of()), input,
                    LiliTurnContract.REPLY_NAME, LiliTurnContract.replySchema());
            lili.record(LiliTurns.Stage.PLAN_FAILURE, LiliPrompts.Prompt.FOLLOWUP, completion, elapsed(started));
            return List.of(lili.reply(completion.content()).cut());
        } catch (Exception exception) {
            lili.record(LiliTurns.Stage.PLAN_FAILURE, LiliPrompts.Prompt.FOLLOWUP, null, elapsed(started));
            return List.of(LiliFixedLines.line(LiliFixedLines.Line.PLAN_UNAVAILABLE));
        }
    }

    // The job keeps LiLi's query and the app's free text, not the user's sentence; they say what the user wanted planned.
    private static String askedFor(GeneratePlanRequest request) {
        String wanted = Stream.of(request.searchQuery(), request.context().additionalRequest())
                .filter(Objects::nonNull)
                .map(String::strip)
                .filter(text -> !text.isEmpty())
                .reduce((first, second) -> first + " " + second)
                .orElse("");
        return wanted.isEmpty() ? TRIP_REQUEST : TRIP_REQUEST + ": " + wanted;
    }

    private static double elapsed(long started) {
        return (System.nanoTime() - started) / 1_000_000.0;
    }
}
