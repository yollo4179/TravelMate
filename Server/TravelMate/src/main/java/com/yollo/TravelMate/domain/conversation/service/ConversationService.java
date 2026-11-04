package com.yollo.TravelMate.domain.conversation.service;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.TokenBudgetException;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationGenerationPipeline;
import com.yollo.TravelMate.domain.conversation.pipeline.ModelModule;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class ConversationService {
    private static final Map<ResultType, Integer> PRIORITY = Map.of(
            ResultType.ERROR, 0, ResultType.TEXT, 0, ResultType.PLACES, 1, ResultType.PLANNING_JOB, 2, ResultType.DRAFT, 3
    );
    private final ConversationGenerationPipeline generation;
    private final ConversationToolRegistry registry;
    private final ConversationToolExecutor executor;
    private final ConversationAnswerRenderer renderer;
    private final ObjectMapper mapper;
    private final ConversationEvidencePreparation evidencePreparation;
    private final int maxModelTurns;
    private final int maxToolCalls;
    public enum ToolFailurePolicy { CONTINUE, STOP }
    private final ToolFailurePolicy toolFailurePolicy;

    public ConversationService(
            LlmClient llm,
            ConversationToolRegistry registry,
            ConversationToolExecutor executor,
            ConversationAnswerRenderer renderer,
            ObjectMapper mapper,
            int maxModelTurns,
            int maxToolCalls,
            ConversationEvidencePreparation evidencePreparation
    ) {
        this(
                llm,
                registry,
                executor,
                renderer,
                mapper,
                maxModelTurns,
                maxToolCalls,
                ToolFailurePolicy.CONTINUE,
                evidencePreparation
        );
    }

    public ConversationService(
            LlmClient llm,
            ConversationToolRegistry registry,
            ConversationToolExecutor executor,
            ConversationAnswerRenderer renderer,
            ObjectMapper mapper,
            int maxModelTurns,
            int maxToolCalls,
            ToolFailurePolicy toolFailurePolicy,
            ConversationEvidencePreparation evidencePreparation
    ) {
        this(
                ConversationGenerationPipeline.defaults(llm),
                registry,
                executor,
                renderer,
                mapper,
                maxModelTurns,
                maxToolCalls,
                toolFailurePolicy,
                evidencePreparation
        );
    }

    @Autowired
    public ConversationService(
            ConversationGenerationPipeline generation,
            ConversationToolRegistry registry,
            ConversationToolExecutor executor,
            ConversationAnswerRenderer renderer,
            ObjectMapper mapper,
            @Value("${travelmate.conversation.max-model-turns:6}") int maxModelTurns,
            @Value("${travelmate.conversation.max-tool-calls:8}") int maxToolCalls,
            @Value("${travelmate.conversation.tool-failure-policy:CONTINUE}") ToolFailurePolicy toolFailurePolicy,
            ConversationEvidencePreparation evidencePreparation
    ) {
        if (maxModelTurns < 1 || maxToolCalls < 1) throw new IllegalArgumentException("도구 루프 한도는 양수여야 합니다.");
        this.generation = java.util.Objects.requireNonNull(generation);
        this.registry = registry;
        this.executor = executor;
        this.renderer = renderer;
        this.mapper = mapper;
        this.maxModelTurns = maxModelTurns;
        this.maxToolCalls = maxToolCalls;
        this.toolFailurePolicy = java.util.Objects.requireNonNull(toolFailurePolicy);
        this.evidencePreparation = java.util.Objects.requireNonNull(evidencePreparation);
    }

    public ConversationResponse respond(String userUid, UUID turnKey, ConversationRequest request) {
        try (var scope = ObservationContext.open(ObservationContext.child(
                ObservationContext.Phase.CONVERSATION, null, null, null))) {
            var response = run(userUid, turnKey, request);
            ObservationContext.record(ObservationContext.Event.TURN_RESULT, mapper.valueToTree(response));
            return response;
        }
    }

    private ConversationResponse run(String userUid, UUID turnKey, ConversationRequest request) {
        long preparationStarted = System.nanoTime();
        var prepared = evidencePreparation.prepare(userUid, turnKey, request, registry);
        var preparationEvent = mapper.createObjectNode().put("state", prepared.state().name())
                .put("sourceTool", prepared.source() == null ? null : prepared.source().wireName())
                .put("durationMs", (System.nanoTime() - preparationStarted) / 1_000_000.0);
        if (prepared.result() != null) {
            preparationEvent.set("modelData", prepared.result().modelData());
            preparationEvent.set("publicData", prepared.result().publicData());
        }
        preparationEvent.set("generationModules", mapper.valueToTree(generation.selection()));
        ObservationContext.record(ObservationContext.Event.EVIDENCE_PREPARATION, preparationEvent);
        List<LlmMessage> messages = new ArrayList<>();
        messages.add(LlmMessage.text(LlmMessage.Role.SYSTEM, generation.systemPrompt(request)));
        request.history().forEach(message -> messages.add(LlmMessage.text(
                LlmMessage.Role.valueOf(message.role().name()), message.content())));
        var userInput = mapper.createObjectNode().put("message", request.message());
        userInput.put("intentHint", request.intentHint().name());
        userInput.set("planningRequest", mapper.valueToTree(request.planningRequest()));
        userInput.set("searchContext", mapper.valueToTree(request.searchContext()));
        if (prepared.result() != null) {
            var serverEvidence = mapper.createObjectNode().put("state", prepared.state().name())
                    .put("sourceTool", prepared.source().wireName());
            serverEvidence.set("data", prepared.result().modelData());
            userInput.set("serverEvidence", serverEvidence);
        }
        messages.add(LlmMessage.text(LlmMessage.Role.USER, userInput.toString()));
        List<ToolObservation> observations = new ArrayList<>();
        Map<String, ConversationTool.Result> cache = new LinkedHashMap<>();
        Map<String, CitationSource> sources = new LinkedHashMap<>();
        if (prepared.result() != null) sources.putAll(prepared.result().sources());
        Set<String> usedCallIds = new HashSet<>();
        ConversationTool.Result primary = prepared.result();
        for (int turn = 1; turn <= maxModelTurns; turn++) {
            final LlmTurn completion;
            try (var scope = ObservationContext.open(ObservationContext.child(
                    ObservationContext.Phase.CONVERSATION, null, null, turn))) {
                completion = generation.execute(new ModelModule.Input(messages, registry.definitions()));
                if (completion == null) throw new IllegalStateException("모델 응답이 없습니다.");
                var observedTurn = mapper.createObjectNode().put("modelTurn", turn).put("content", completion.content());
                observedTurn.set("toolCalls", mapper.valueToTree(completion.toolCalls()));
                ObservationContext.record(ObservationContext.Event.MODEL_TURN, observedTurn);
            } catch (RuntimeException exception) {
                Termination termination = exception instanceof TokenBudgetException budget
                        ? (budget.reason() == TokenBudgetException.Reason.COUNT_UNAVAILABLE
                            ? Termination.COUNT_UNAVAILABLE : Termination.BUDGET_REJECTED) : Termination.MODEL_FAILED;
                return renderer.render(primary, null, termination, turn, observations);
            }
            if (completion.toolCalls().isEmpty()) {
                try {
                    var answer = renderer.parse(completion.content(), sources);
                    if (observations.isEmpty()
                            && answer.answerKind() != ConversationAnswerRenderer.AnswerKind.PLACE_GUIDANCE) primary = null;
                    return renderer.render(primary, answer, Termination.COMPLETED, turn, observations);
                } catch (Exception exception) {
                    return renderer.render(primary, null, Termination.INVALID_RESPONSE, turn, observations);
                }
            }
            if (prepared.retrievalCalls() + observations.size() + completion.toolCalls().size() > maxToolCalls) {
                return renderer.render(primary, null, Termination.TOOL_LIMIT, turn, observations);
            }
            if (!validCallIds(completion.toolCalls(), usedCallIds)) {
                return renderer.render(primary, null, Termination.INVALID_RESPONSE, turn, observations);
            }
            final ToolContinuation continuation;
            try {
                continuation = ToolContinuation.parse(completion.content(), mapper);
            } catch (Exception exception) {
                return renderer.render(primary, null, Termination.INVALID_RESPONSE, turn, observations);
            }
            messages.add(LlmMessage.assistant(completion));
            boolean toolFailed = false;
            for (var call : completion.toolCalls()) {
                var invocation = ConversationTool.Invocation.builder().userUid(userUid).turnKey(turnKey).request(request).build();
                long toolStarted = System.nanoTime();
                final ConversationToolExecutor.Executed executed;
                try (var scope = ObservationContext.open(ObservationContext.child(
                        ObservationContext.Phase.CONVERSATION, null, call.id(), turn))) {
                    executed = executor.execute(call, invocation, cache);
                }
                var result = executed.result();
                var observation = new ToolObservation(call.id(), call.name(), call.arguments(), executed.status(),
                        result.type(), result.publicData(), UUID.randomUUID().toString());
                observations.add(observation);
                var toolEvent = mapper.createObjectNode().put("durationMs", (System.nanoTime() - toolStarted) / 1_000_000.0);
                toolEvent.set("result", mapper.valueToTree(observation));
                toolEvent.set("modelData", result.modelData());
                ObservationContext.record(ObservationContext.Event.TOOL_RESULT, toolEvent);
                if (primary == null || PRIORITY.get(result.type()) >= PRIORITY.get(primary.type())) primary = result;
                toolFailed |= executed.status() == ToolStatus.FAILED;
                if (toolFailurePolicy == ToolFailurePolicy.STOP && executed.status() == ToolStatus.FAILED) {
                    return renderer.receipt(primary, Termination.TOOL_FAILED, turn, observations);
                }
                sources.putAll(result.sources());
                var feedback = mapper.createObjectNode().put("type", result.type().name());
                feedback.set("data", result.modelData());
                messages.add(LlmMessage.tool(call, feedback.toString()));
            }
            if (continuation == ToolContinuation.RETURN_RESULT) {
                return renderer.receipt(
                        primary,
                        toolFailed ? Termination.TOOL_FAILED : Termination.COMPLETED,
                        turn,
                        observations
                );
            }
        }
        return renderer.render(primary, null, Termination.MODEL_LIMIT, maxModelTurns, observations);
    }

    private static boolean validCallIds(List<LlmTurn.ToolCall> calls, Set<String> usedCallIds) {
        Set<String> nextIds = new HashSet<>();
        for (var call : calls) {
            if (call.id() == null || call.id().isBlank() || call.id().length() > 128
                    || call.name() == null || call.name().isBlank() || call.name().length() > 128
                    || usedCallIds.contains(call.id()) || !nextIds.add(call.id())) return false;
        }
        usedCallIds.addAll(nextIds);
        return true;
    }
}
