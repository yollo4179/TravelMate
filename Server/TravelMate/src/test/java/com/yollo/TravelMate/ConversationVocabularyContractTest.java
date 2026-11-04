package com.yollo.TravelMate;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.conversation.data.*;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.*;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationModuleConfig;
import com.yollo.TravelMate.domain.conversation.pipeline.PromptTemplates;
import com.yollo.TravelMate.domain.conversation.pipeline.ResourcePromptV1;
import com.yollo.TravelMate.domain.conversation.service.ConversationAnswerRenderer;
import com.yollo.TravelMate.domain.conversation.service.PlaceConversationEvidence;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchContext;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.prompts.GeneratedPlanOutputContract;
import com.yollo.TravelMate.domain.plan.prompts.PlanPrompts;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.DefaultResourceLoader;
import static org.junit.jupiter.api.Assertions.*;

class ConversationVocabularyContractTest {
    private final ObjectMapper mapper = new ObjectMapper();

    private static String joined(List<? extends Enum<?>> values) {
        return values.stream().map(Enum::name).collect(Collectors.joining("/"));
    }

    @Test
    void defaultPromptListsExactlyTheEnforcedEnumValues() {
        String prompt = new ResourcePromptV1(ConversationModuleConfig.defaults(), new DefaultResourceLoader()).execute(null, null);
        assertFalse(prompt.contains("{{"), "every prompt token must be rendered");
        assertTrue(prompt.contains("intentHint는 " + joined(Arrays.asList(ConversationIntent.values())) + " 중"));
        assertTrue(prompt.contains("intent는 " + joined(ConversationIntent.finalValues()) + " 중"));
        assertTrue(prompt.contains("answerKind는 " + joined(Arrays.asList(ConversationAnswerKind.values())) + ","));
        assertTrue(prompt.contains("emotion은 " + joined(Arrays.asList(CharacterEmotion.values())) + " 중"));
        assertTrue(prompt.contains(joined(PlanningResponse.JobStatus.pendingValues()) + "는 완성된"));
        assertTrue(prompt.contains("answerKind/citations/emotion/intent/message 필드만"));
        Arrays.stream(ConversationTool.Name.values()).forEach(name -> assertTrue(prompt.contains(name.wireName())));
    }

    @Test
    void unknownPromptTokenFailsBeforeAnyModelCall() {
        assertThrows(IllegalArgumentException.class, () -> PromptTemplates.render("값: {{inventedToken}}", Map.of()));
        assertEquals("{{그대로}} 둔다", PromptTemplates.render("{{message}}", Map.of("message", "{{그대로}} 둔다")));
    }

    @Test
    void themeHintComesFromTheResourceAndKeepsThePreviousQueryText() {
        AtomicReference<String> query = new AtomicReference<>();
        var definition = new SearchPlacesTool(null, null, null, mapper).definition();
        ConversationTool capturing = new ConversationTool() {
            @Override
            public LlmTurn.ToolDefinition definition() {
                return definition;
            }

            @Override
            public Result execute(Invocation invocation) {
                query.set(invocation.arguments().path("query").asText());
                return Result.builder().type(ResultType.PLACES).publicData(mapper.createArrayNode()).modelData(mapper.createObjectNode()).build();
            }
        };
        var registry = new ConversationToolRegistry(List.of(capturing));
        var evidence = new PlaceConversationEvidence(mapper, new DefaultResourceLoader(), "classpath:conversation/queries/v1-theme-hint.txt");
        var themed = new PlaceSearchContext(null, null, null, List.of(), null, List.of("역사", "산책"));
        evidence.prepare("user", null, new ConversationRequest("조용한 궁", null, List.of(), themed), registry);
        assertEquals("조용한 궁\n사용자 선호 테마: 역사, 산책", query.get());
        evidence.prepare("user", null, new ConversationRequest("조용한 궁", null, List.of()), registry);
        assertEquals("조용한 궁", query.get());
    }

    @Test
    void planOutputRequiresAnEmotionFromTheSameEnumAndThePromptNamesIt() throws Exception {
        var schema = GeneratedPlanOutputContract.schema();
        assertTrue(List.of(mapper.treeToValue(schema.path("required"), String[].class)).contains("emotion"));
        assertEquals(joined(Arrays.asList(CharacterEmotion.values())),
                String.join("/", mapper.treeToValue(schema.path("properties").path("emotion").path("enum"), String[].class)));
        String emotionRule = "emotion은 " + joined(Arrays.asList(CharacterEmotion.values()));
        // The legacy planner path parses the same enum, so its shared prompt must list the tags too.
        assertTrue(PlanPrompts.PLANNER_SYSTEM.contains(emotionRule));
        assertTrue(new ContextPlanPromptFactory(mapper).systemPrompt().contains(emotionRule));
        var parsed = mapper.readValue("{\"planTitle\":\"t\",\"planDescription\":\"d\",\"pins\":[],\"emotion\":\"AFFECTIONATE\"}", GeneratedPlan.class);
        assertEquals(CharacterEmotion.AFFECTIONATE, parsed.emotion());
        assertThrows(Exception.class, () -> mapper.readValue("{\"planTitle\":\"t\",\"pins\":[],\"emotion\":\"INVENTED\"}", GeneratedPlan.class));
    }

    @Test
    void draftReceiptUsesThePlanModelEmotionAndFallsBackForOlderDrafts() throws Exception {
        var renderer = new ConversationAnswerRenderer(mapper);
        var chosen = ConversationTool.Result.builder().type(ResultType.DRAFT)
                .publicData(mapper.readTree("{\"planId\":1,\"pins\":[],\"emotion\":\"AFFECTIONATE\"}")).build();
        assertEquals(CharacterEmotion.AFFECTIONATE, renderer.receipt(chosen, Termination.COMPLETED, 1, List.of()).emotion());
        var older = ConversationTool.Result.builder().type(ResultType.DRAFT)
                .publicData(mapper.readTree("{\"planId\":1,\"pins\":[]}")).build();
        assertEquals(CharacterEmotion.EXCITED, renderer.receipt(older, Termination.COMPLETED, 1, List.of()).emotion());
    }
}
