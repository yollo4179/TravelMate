package com.yollo.TravelMate;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.place.data.response.PlaceSearchResponseDto;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class FrozenOriginalFieldPipelineTest {
    private final JsonMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();

    @Test
    void evaluationDatabaseMockKafkaOriginalsReachTheConversationModelWithoutSupplement() throws Exception {
        var resource = getClass().getResourceAsStream("/frozen-original-field-kafka.json");
        assertNotNull(resource);
        ObjectNode event;
        try (resource) { event = (ObjectNode) mapper.readTree(resource); }
        var results = new SearchEvidencePipelineTest().consume(event);
        var searches = mock(PlaceSemanticSearchService.class);
        when(searches.search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class))).thenReturn(results);
        var llm = mock(LlmClient.class);
        AtomicInteger turns = new AtomicInteger();
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            if (turns.getAndIncrement() == 0) {
                return LlmTurn.builder().toolCalls(List.of(new LlmTurn.ToolCall("frozen-search", "search_places",
                        "{\"query\":\"동결 장소 설명\",\"limit\":2}"))).build();
            }
            List<LlmMessage> messages = invocation.getArgument(0);
            Path captureDirectory = Path.of("build", "original-fields-mock");
            Files.createDirectories(captureDirectory);
            mapper.writerWithDefaultPrettyPrinter().writeValue(captureDirectory.resolve("llm-input.json").toFile(),
                    mapper.createObjectNode().put("mode", "MOCK").put("scope", "transport regression, not a B quality case")
                            .set("messages", mapper.valueToTree(messages)));
            JsonNode candidates = mapper.readTree(messages.get(messages.size() - 1).content()).path("data").path("candidates");
            for (int index = 0; index < results.size(); index++) {
                var candidate = candidates.get(index);
                var evidence = candidate.path("selectedEvidence").get(0);
                var original = evidence.path("original");
                var expected = results.get(index).evidenceChunks().get(0);
                String text = expected.toJson().path("chunk_text").asText();
                assertEquals(text, original.path("chunk_text").asText());
                assertEquals("tourapi", original.path("source_type").asText());
                assertEquals("1.4.0", original.path("metadata").path("snapshot_version").asText());
                assertEquals(expected.toJson().path("metadata"), original.path("metadata"));
                assertEquals(results.get(index).place().id().longValue(), original.path("metadata").path("place_id").asLong());
                assertEquals(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8))),
                        original.path("metadata").path("content_sha256").asText());
                assertEquals(0, evidence.path("generatedSupplement").size());
                assertFalse(evidence.path("annotations").has("relations"));
                assertFalse(original.path("metadata").has("source_url"));
                assertFalse(original.path("metadata").has("collected_at"));
                assertEquals("NOT_EMBEDDED", evidence.path("retrieval").path("vector_binding").asText());
                assertEquals("place_candidate", evidence.path("retrieval").path("semantic_score_scope").asText());
                assertTrue(expected.permitsQuote(results.get(index).place().id(), text));
                assertFalse(expected.permitsQuote(-1L, text));
                if (text.codePointCount(0, text.length()) > 400) {
                    assertTrue(candidate.path("description").asText().length() <= 400);
                    assertTrue(original.path("chunk_text").asText().length() > 400);
                }
            }
            return LlmTurn.builder().content("{\"message\":\"동결 TourAPI 설명을 전달받았습니다.\",\"citations\":[]}").build();
        });
        var prompts = new ContextPlanPromptFactory(mapper);
        var registry = new ConversationToolRegistry(List.of(new SearchPlacesTool(searches, new PlaceSearchCriteriaResolver(), prompts, mapper)), "SEARCH_PLACES");
        var service = new ConversationService(llm, registry, new ConversationToolExecutor(registry, mapper),
                new ConversationAnswerRenderer(mapper), mapper, 2, 1, ConversationService.ToolFailurePolicy.STOP);
        var response = service.respond("mock-owner", UUID.randomUUID(), new ConversationRequest("동결 장소 설명", null, List.of()));
        assertEquals(ConversationResponse.Termination.COMPLETED, response.termination());
        assertEquals(mapper.valueToTree(results.stream().map(PlaceSearchResponseDto::from).toList()), response.data());
        verify(llm, times(2)).chat(anyList(), anyList());
        verifyNoMoreInteractions(llm);
    }
}
