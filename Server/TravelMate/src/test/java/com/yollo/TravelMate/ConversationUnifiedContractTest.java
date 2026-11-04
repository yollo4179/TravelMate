package com.yollo.TravelMate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.*;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.*;
import com.yollo.TravelMate.domain.conversation.service.ConversationAnswerRenderer;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.conversation.controller.ConversationOptionsController;
import com.yollo.TravelMate.ai.llm.derived.OpenAiToolContracts;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ConversationUnifiedContractTest {
    private final ObjectMapper mapper = new ObjectMapper();
    @Test
    void originalAssetsAndEmotionsMatchExactly() throws Exception {
        var root = Path.of("../../Resouces/Images/LiLi");
        var catalog = mapper.readTree(root.resolve("catalog.json").toFile());
        var tags = new java.util.HashSet<String>();
        for (var entry : catalog.path("assets")) {
            assertTrue(tags.add(entry.path("emotion").asText()));
            assertEquals(entry.path("sha256").asText(), java.util.HexFormat.of().formatHex(
                    java.security.MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(root.resolve(entry.path("file").asText())))));
        }
        assertEquals(Set.of(CharacterEmotion.values()).stream().map(Enum::name).collect(java.util.stream.Collectors.toSet()), tags);
        assertEquals(10, tags.size());
    }
    @Test
    void allThreeToolsAreStrictAndInvalidJobArgumentsAreRejected() {
        var registry = new ConversationToolRegistry(List.of(new SearchPlacesTool(null, null, null, mapper), new GeneratePlanTool(null, null), new GetPlanningJobTool(null, null)));
        var prepared = OpenAiToolContracts.prepare(registry.definitions(), OpenAiToolContracts.Mode.STRICT_TOOLS_V1);
        assertEquals(3, prepared.size());
        assertTrue(prepared.stream().allMatch(OpenAiToolContracts.PreparedTool::strict));
        for (var tool : prepared) {
            assertFalse(tool.parameters().path("additionalProperties").asBoolean());
            assertEquals(tool.parameters().path("properties").size(), tool.parameters().path("required").size());
        }
        var job = prepared.stream().filter(tool -> tool.definition().name().equals("get_planning_job")).findFirst().orElseThrow();
        assertThrows(IllegalArgumentException.class, () -> job.adapt(new com.yollo.TravelMate.ai.llm.base.LlmTurn.ToolCall("bad", "get_planning_job", "{}")));
    }
    @Test
    void singlePlaceAndSingleDraftAreArraysWithAuthoritativeData() throws Exception {
        var renderer = new ConversationAnswerRenderer(mapper);
        for (var result : List.of(
                ConversationTool.Result.builder().type(ResultType.PLACES).publicData(mapper.readTree("[{\"placeId\":378}]")).build(),
                ConversationTool.Result.builder().type(ResultType.DRAFT).publicData(mapper.readTree("{\"planId\":1,\"pins\":[]}")).build())) {
            var response = renderer.receipt(result, Termination.COMPLETED, 1, List.of());
            assertEquals(1, response.items().size());
            assertNotNull(response.emotion());
            assertFalse(response.message().isBlank());
            assertEquals(result.publicData(), response.data());
        }
    }
    @Test
    void finalAnswerPreservesEmotionAndRejectsUnknownTag() throws Exception {
        var renderer = new ConversationAnswerRenderer(mapper);
        String content = "{\"message\":\"다음 여행도 함께 준비해요.\",\"citations\":[],\"answerKind\":\"CONVERSATION\",\"emotion\":\"HAPPY\"}";
        var response = renderer.render(null, renderer.parse(content, Map.of()), Termination.COMPLETED, 1, List.of());
        assertEquals(CharacterEmotion.HAPPY, response.emotion());
        assertEquals(ConversationIntent.CONVERSATION, response.intent());
        assertEquals(List.of(), response.items());
        assertThrows(Exception.class, () -> renderer.parse(content.replace("HAPPY", "INVENTED"), Map.of()));
    }
    @Test
    void planningClarificationRemainsPlanIntentAndStoredDraftExplanationIsReturned() throws Exception {
        var renderer = new ConversationAnswerRenderer(mapper);
        var answer = renderer.parse("{\"message\":\"시작 시간을 알려주세요.\",\"citations\":[],\"answerKind\":\"CLARIFICATION\",\"emotion\":\"THINKING\",\"intent\":\"PLAN\"}", Map.of());
        assertEquals(ConversationIntent.PLAN, renderer.render(null, answer, Termination.COMPLETED, 1, List.of()).intent());
        var result = ConversationTool.Result.builder().type(ResultType.DRAFT)
                .publicData(mapper.readTree("{\"description\":\"요청한 역사 테마의 초안입니다.\",\"pins\":[]}")).build();
        assertEquals("요청한 역사 테마의 초안입니다.", renderer.receipt(result, Termination.COMPLETED, 1, List.of()).message());
    }

    @Test
    void uiCategoriesAreDerivedFromStorageEnum() {
        var options = new ConversationOptionsController().options();
        assertEquals(com.yollo.TravelMate.domain.place.enums.PlaceSearchCategories.allowedValues(), options.get("categories"));
        assertEquals(4, ((List<?>) options.get("intents")).size());
        assertEquals(10, ((List<?>) options.get("emotions")).size());
    }
}
