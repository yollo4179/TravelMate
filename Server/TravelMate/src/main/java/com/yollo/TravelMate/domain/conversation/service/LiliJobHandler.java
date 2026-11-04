package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** The server, not the model, takes the job ID from the user's words; LiLi then explains the real status. */
@Component
@RequiredArgsConstructor
public class LiliJobHandler implements LiliBranchHandler {
    // Not \b: Java treats Hangul as word characters, so "<id>의" would never match.
    private static final Pattern JOB_ID = Pattern.compile(
            "(?<![0-9a-fA-F-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F-])");
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
        List<String> ids = JOB_ID.matcher(turn.request().message()).results()
                .map(match -> match.group().toLowerCase(Locale.ROOT)).distinct().toList();
        if (ids.size() != 1) {
            var missing = mapper.createObjectNode().put("code", LiliServerCode.JOB_ID_NOT_FOUND.name());
            return actions.followUp(turn, ResultType.ERROR, missing)
                    .map(reply -> renderer.dialogue(null, reply.intent(), List.of(), List.of(reply.cut()),
                            reply.choices(), Termination.COMPLETED, 2, List.of()))
                    .orElseGet(() -> renderer.render(null, null, Termination.INVALID_RESPONSE, 2, List.of()));
        }
        var executed = actions.run(turn, turn.request(), ConversationTool.Name.GET_PLANNING_JOB,
                mapper.createObjectNode().put("job_id", ids.get(0)));
        Termination termination = executed.failed() ? Termination.TOOL_FAILED : Termination.COMPLETED;
        return actions.followUp(turn, executed.result().type(), executed.result().modelData())
                .map(reply -> renderer.dialogue(executed.result(), reply.intent(), List.of(), List.of(reply.cut()),
                        reply.choices(), termination, 2, List.of(executed.observation())))
                .orElseGet(() -> renderer.receipt(executed.result(), termination, 1, List.of(executed.observation())));
    }
}
