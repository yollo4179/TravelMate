package com.yollo.TravelMate.domain.conversation.service;

import java.util.ArrayList;
import java.util.List;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliFixedLines;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * The server, not the model, takes the job ID from the user's words. A known status is told with LiLi's fixed
 * line after her router cut; only failures go back to her follow-up, with a user-facing reason.
 */
@Component
@RequiredArgsConstructor
public class LiliJobHandler implements LiliBranchHandler {
    private static final int ROUTER_TURNS = 1;
    private static final int FOLLOW_UP_TURNS = 2;
    private final LiliActions actions;
    private final ConversationAnswerRenderer renderer;
    private final ObjectMapper mapper;

    @Override
    public boolean supports(LiliBranch branch) {
        return branch == LiliBranch.GET_PLANNING_JOB;
    }

    @Override
    public ConversationResponse execute(Input input) {
        var turn = input.turn();
        var jobId = PlanningJobReference.single(turn.request().message());
        if (jobId.isEmpty()) return followUp(input, LiliServerCode.JOB_ID_NOT_FOUND, null, null, Termination.COMPLETED);
        var executed = actions.run(turn, turn.request(), ConversationTool.Name.GET_PLANNING_JOB,
                mapper.createObjectNode().put("job_id", jobId.get().toString()));
        var result = executed.result();
        if (executed.failed()) {
            return followUp(input, LiliServerCode.JOB_LOOKUP_FAILED, result.modelData().path("message").asText(null),
                    executed, Termination.TOOL_FAILED);
        }
        if (result.type() == ResultType.DRAFT) return told(input, executed, draftCuts(result.publicData()));
        var status = JobStatus.valueOf(result.publicData().path("status").asText());
        if (status == JobStatus.FAILED) {
            // The job already holds LiLi's reaction to the failure the server verified; asking her again adds a call.
            var reaction = storedCuts(result.publicData().path("dialogue"));
            if (!reaction.isEmpty()) return told(input, executed, reaction);
            return followUp(input, LiliServerCode.PLAN_GENERATION_FAILED,
                    result.publicData().path("errorMessage").asText(null), executed, Termination.COMPLETED);
        }
        return told(input, executed, List.of(LiliFixedLines.line(status)));
    }

    private ConversationResponse told(Input input, LiliActions.Executed executed, List<DialogueCut> statusCuts) {
        var dialogue = new ArrayList<DialogueCut>();
        dialogue.add(input.decision().cut());
        dialogue.addAll(statusCuts);
        return renderer.dialogue(executed.result(), input.decision().intent(), List.of(), dialogue, List.of(),
                Termination.COMPLETED, ROUTER_TURNS, List.of(executed.observation()));
    }

    // The plan model already wrote LiLi's cuts for the draft; older drafts without cuts get the fixed line.
    private List<DialogueCut> draftCuts(JsonNode draft) {
        var cuts = storedCuts(draft.path("dialogue"));
        return cuts.isEmpty() ? List.of(LiliFixedLines.line(JobStatus.SUCCEEDED)) : cuts;
    }

    private static List<DialogueCut> storedCuts(JsonNode stored) {
        if (!stored.isArray()) return List.of();
        var cuts = new ArrayList<DialogueCut>();
        stored.forEach(cut -> cuts.add(new DialogueCut(cut.path("text").asText(),
                CharacterEmotion.valueOf(cut.path("emotion").asText()))));
        return cuts;
    }

    private ConversationResponse followUp(
            Input input,
            LiliServerCode code,
            String userFacingReason,
            LiliActions.Executed executed,
            Termination termination
    ) {
        var primary = executed == null ? null : executed.result();
        var observations = executed == null ? List.<ConversationResponse.ToolObservation>of() : List.of(executed.observation());
        return actions.followUp(input.turn(), code, userFacingReason)
                .map(reply -> renderer.dialogue(primary, reply.intent(), List.of(), List.of(reply.cut()),
                        reply.choices(), termination, FOLLOW_UP_TURNS, observations))
                .orElseGet(() -> primary == null
                        ? renderer.liliFallback(null, Termination.INVALID_RESPONSE, FOLLOW_UP_TURNS, List.of())
                        : renderer.receipt(primary, termination, ROUTER_TURNS, observations));
    }
}
