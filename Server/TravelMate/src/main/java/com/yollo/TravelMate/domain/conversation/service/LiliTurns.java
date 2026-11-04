package com.yollo.TravelMate.domain.conversation.service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmMessage;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.base.StructuredOutput;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.ConversationAnswerKind;
import com.yollo.TravelMate.domain.conversation.data.ConversationIntent;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Citation;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationGenerationPipeline;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliPrompts;
import com.yollo.TravelMate.domain.conversation.pipeline.ModelModule;
import com.yollo.TravelMate.domain.conversation.tool.ToolSchemas;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource;
import com.yollo.TravelMate.domain.plan.validator.PlanEvidenceCitationValidator;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** Calls LiLi with a versioned prompt and Strict schema, then validates the reply on the server again. */
@Component
@RequiredArgsConstructor
public class LiliTurns {
    private final ConversationGenerationPipeline generation;
    private final ObjectMapper mapper;

    public enum Stage { ROUTER, FOLLOW_UP, RECOMMENDATION }

    public record Decision(
            LiliBranch branch,
            ConversationIntent intent,
            String searchQuery,
            List<Integer> excludePositions,
            CharacterEmotion emotion,
            String message,
            List<String> choices
    ) {
        public DialogueCut cut() {
            return new DialogueCut(message, emotion);
        }
    }

    public record Reply(
            ConversationIntent intent,
            CharacterEmotion emotion,
            String message,
            List<String> choices
    ) {
        public DialogueCut cut() {
            return new DialogueCut(message, emotion);
        }

        public Reply withoutChoices() {
            return new Reply(intent, emotion, message, List.of());
        }
    }

    public record Recommendation(
            ConversationIntent intent,
            ConversationAnswerKind answerKind,
            List<Citation> citations,
            List<DialogueCut> dialogue
    ) {}

    public LlmTurn call(
            LiliPrompts.Prompt prompt,
            ConversationRequest request,
            JsonNode userInput,
            String outputName,
            JsonNode outputSchema
    ) {
        List<LlmMessage> messages = new ArrayList<>();
        messages.add(LlmMessage.text(LlmMessage.Role.SYSTEM, LiliPrompts.text(prompt)));
        request.history().forEach(message -> messages.add(LlmMessage.text(
                LlmMessage.Role.valueOf(message.role().name()), message.content())));
        messages.add(LlmMessage.text(LlmMessage.Role.USER, userInput.toString()));
        return generation.execute(new ModelModule.Input(messages, List.of(), new StructuredOutput(outputName, outputSchema)));
    }

    /** ROUTE for LiLi's first decision, MODEL_TURN for later calls, so evaluators can tell them apart. */
    public void record(Stage stage, LiliPrompts.Prompt prompt, LlmTurn completion, double durationMs) {
        var event = mapper.createObjectNode().put("stage", stage.name()).put("prompt", prompt.name())
                .put("promptSha256", LiliPrompts.sha256(prompt)).put("durationMs", durationMs)
                .put("content", completion == null ? null : completion.content());
        if (stage == Stage.ROUTER) {
            ObservationContext.record(ObservationContext.Event.ROUTE, event);
            return;
        }
        event.set("toolCalls", mapper.createArrayNode());
        ObservationContext.record(ObservationContext.Event.MODEL_TURN, event);
    }

    public Decision decision(String content) throws Exception {
        JsonNode node = strict(content, LiliTurnContract.routerSchema());
        var branch = LiliBranch.valueOf(node.get("branch").asText());
        String query = node.get("search_query").isNull() ? null : node.get("search_query").asText().strip();
        if (branch.requiresSearchQuery() && (query == null || query.isBlank())) {
            throw new IllegalArgumentException("A search or plan branch needs a search query");
        }
        return new Decision(
                branch,
                ConversationIntent.valueOf(node.get("intent").asText()),
                branch.requiresSearchQuery() ? query : null,
                // Positions only mean something for a search over the list the user is looking at.
                branch == LiliBranch.SEARCH_PLACES ? positions(node.get("exclude_positions")) : List.of(),
                CharacterEmotion.valueOf(node.get("emotion").asText()),
                node.get("message").asText().strip(),
                branch == LiliBranch.CLARIFY ? texts(node.get("choices")) : List.of()
        );
    }

    public Reply reply(String content) throws Exception {
        JsonNode node = strict(content, LiliTurnContract.replySchema());
        return new Reply(
                ConversationIntent.valueOf(node.get("intent").asText()),
                CharacterEmotion.valueOf(node.get("emotion").asText()),
                node.get("message").asText().strip(),
                texts(node.get("choices"))
        );
    }

    public Recommendation recommendation(String content, Map<String, CitationSource> sources) throws Exception {
        JsonNode node = strict(content, LiliTurnContract.recommendationSchema());
        List<Citation> citations = new ArrayList<>();
        for (JsonNode item : node.get("citations")) {
            long placeId = item.get("placeId").asLong();
            // The same membership rule as grounded answers; the stored quote is the original's own span.
            var verified = PlanEvidenceCitationValidator.validate(placeId, new GeneratedPlan.SourceCitation(
                    item.get("evidenceId").asText(), item.get("sourceId").asText(), item.get("quote").asText()), sources);
            citations.add(new Citation(placeId, verified.evidenceId(), verified.sourceId(), verified.quote()));
        }
        List<DialogueCut> dialogue = new ArrayList<>();
        node.get("dialogue").forEach(cut -> dialogue.add(new DialogueCut(cut.get("text").asText().strip(),
                CharacterEmotion.valueOf(cut.get("emotion").asText()))));
        return new Recommendation(
                ConversationIntent.valueOf(node.get("intent").asText()),
                ConversationAnswerKind.valueOf(node.get("answerKind").asText()),
                List.copyOf(citations),
                List.copyOf(dialogue)
        );
    }

    private JsonNode strict(String content, JsonNode schema) throws Exception {
        JsonNode node = mapper.reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(content);
        if (node == null) throw new IllegalArgumentException("LiLi returned no JSON");
        ToolSchemas.validate(schema, node);
        return node;
    }

    private static List<Integer> positions(JsonNode array) {
        List<Integer> values = new ArrayList<>();
        array.forEach(value -> values.add(value.intValue()));
        return List.copyOf(values);
    }

    private static List<String> texts(JsonNode array) {
        List<String> values = new ArrayList<>();
        array.forEach(value -> values.add(value.asText().strip()));
        return List.copyOf(values);
    }
}
