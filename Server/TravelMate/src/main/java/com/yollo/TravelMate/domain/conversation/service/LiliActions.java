package com.yollo.TravelMate.domain.conversation.service;

import java.util.LinkedHashMap;
import java.util.Optional;
import java.util.UUID;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ToolObservation;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ToolStatus;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationRoutingModule;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliPrompts;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** Server-side execution of the tool LiLi chose, and LiLi's follow-up line over the authoritative result. */
@Component
@RequiredArgsConstructor
public class LiliActions {
    public static final String INITIATOR = "LILI";
    private final ConversationToolExecutor executor;
    private final LiliTurns lili;
    private final ObjectMapper mapper;

    public record Executed(ConversationTool.Result result, ToolObservation observation) {
        public boolean failed() {
            return observation.status() == ToolStatus.FAILED;
        }
    }

    public Executed run(
            ConversationRoutingModule.Turn turn,
            ConversationRequest request,
            ConversationTool.Name tool,
            JsonNode arguments
    ) {
        var call = LlmTurn.ToolCall.builder().id("lili-" + UUID.randomUUID()).name(tool.wireName())
                .arguments(arguments.toString()).build();
        var invocation = ConversationTool.Invocation.builder().userUid(turn.userUid()).turnKey(turn.turnKey())
                .request(request).build();
        long started = System.nanoTime();
        var executed = executor.execute(call, invocation, new LinkedHashMap<>());
        var result = executed.result();
        return observe(call.id(), tool, arguments, result, executed.status(), started);
    }

    /** Records a job the server queued itself (no executor tool), with the same event shape as other tools. */
    public Executed queued(
            ConversationTool.Name tool,
            JsonNode arguments,
            ConversationTool.Result result,
            long started
    ) {
        return observe("lili-" + UUID.randomUUID(), tool, arguments, result, ToolStatus.SUCCEEDED, started);
    }

    /**
     * Empty when LiLi's follow-up cannot be used; the caller then falls back to the server receipt.
     * She receives the situation in Korean and a user-facing reason, never internal codes or raw tool payloads.
     */
    public Optional<LiliTurns.Reply> followUp(
            ConversationRoutingModule.Turn turn,
            LiliServerCode code,
            String userFacingReason
    ) {
        var input = mapper.createObjectNode().put("message", turn.request().message());
        input.putObject("serverResult")
                .put("situation", code.situation())
                .put("reason", userFacingReason)
                .put("askUser", code.needsUserInput());
        long started = System.nanoTime();
        try {
            var completion = lili.call(LiliPrompts.Prompt.FOLLOWUP, turn.request(), input,
                    LiliTurnContract.REPLY_NAME, LiliTurnContract.replySchema());
            lili.record(LiliTurns.Stage.FOLLOW_UP, LiliPrompts.Prompt.FOLLOWUP, completion, elapsed(started));
            var reply = lili.reply(completion.content());
            return Optional.of(code.needsUserInput() ? reply : reply.withoutChoices());
        } catch (Exception exception) {
            lili.record(LiliTurns.Stage.FOLLOW_UP, LiliPrompts.Prompt.FOLLOWUP, null, elapsed(started));
            return Optional.empty();
        }
    }

    private Executed observe(
            String callId,
            ConversationTool.Name tool,
            JsonNode arguments,
            ConversationTool.Result result,
            ToolStatus status,
            long started
    ) {
        var observation = new ToolObservation(callId, tool.wireName(), arguments.toString(), status,
                result.type(), result.publicData(), UUID.randomUUID().toString());
        var event = mapper.createObjectNode().put("durationMs", elapsed(started)).put("initiator", INITIATOR);
        event.set("result", mapper.valueToTree(observation));
        event.set("modelData", result.modelData());
        ObservationContext.record(ObservationContext.Event.TOOL_RESULT, event);
        return new Executed(result, observation);
    }

    private static double elapsed(long started) {
        return (System.nanoTime() - started) / 1_000_000.0;
    }
}
