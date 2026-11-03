package com.yollo.TravelMate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.domain.conversation.data.*;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.place.data.result.*;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestFactory;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class SearchToolContractRegressionTest {
    private static final Path LIVE = Path.of("../../Evaluation/runs/contextual/b-live-integration-v1/20261102-01/raw");
    private final JsonMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();
    private final PlaceSearchCriteriaResolver resolver = new PlaceSearchCriteriaResolver();

    @TestFactory
    List<DynamicTest> recordedToolSelectionsReplayOfflineWithoutRepairOrRetry() throws Exception {
        List<DynamicTest> tests = new ArrayList<>();
        for (String line : Files.readAllLines(LIVE.resolve("records-all-observed.jsonl"))) {
            JsonNode record = mapper.readTree(line);
            tests.add(DynamicTest.dynamicTest(record.path("case_id").asText(), () -> replay(record)));
        }
        return tests;
    }

    private void replay(JsonNode record) throws Exception {
        var searches = mock(PlaceSemanticSearchService.class);
        var originalResult = mapper.readTree(LIVE.resolve("PLR-TM-palaces-01.response.json").toFile()).path("data").get(0);
        var place = mapper.treeToValue(mapper.createObjectNode().put("id", originalResult.path("placeId").asLong())
                .put("name", originalResult.path("name").asText()).put("description", originalResult.path("description").asText()), PlaceResult.class);
        var evidence = new SearchEvidenceChunk(originalResult.path("evidenceChunks").get(0));
        when(searches.search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class)))
                .thenReturn(List.of(new PlaceSemanticSearchResult(place, 1f, List.of(evidence))));
        var tool = new SearchPlacesTool(searches, resolver, new ContextPlanPromptFactory(mapper), mapper);
        var registry = new ConversationToolRegistry(List.of(tool), "SEARCH_PLACES");
        var llm = mock(LlmClient.class);
        JsonNode capturedCall = record.path("tool_calls").get(0);
        String rawArguments = capturedCall.path("function").path("arguments").asText();
        var actualCall = new LlmTurn.ToolCall(capturedCall.path("id").asText(), "search_places", rawArguments);
        AtomicInteger turns = new AtomicInteger();
        List<String> capturedFrames = new ArrayList<>();
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            var frame = mapper.createObjectNode().put("mode", "MOCK").put("case_id", record.path("case_id").asText())
                    .put("fixture_source", "8e594546 LIVE record; current messages are offline replay")
                    .put("model_turn", turns.get() + 1);
            frame.set("messages", mapper.valueToTree(invocation.getArgument(0)));
            frame.set("tools", mapper.valueToTree(invocation.getArgument(1)));
            capturedFrames.add(frame.toString());
            if (turns.getAndIncrement() == 0) return LlmTurn.builder().content("{\"afterTool\":\"REASSESS\"}")
                    .toolCalls(List.of(actualCall)).build();
            List<LlmMessage> messages = invocation.getArgument(0);
            JsonNode forwarded = mapper.readTree(messages.get(messages.size() - 1).content())
                    .path("data").path("candidates").get(0).path("selectedEvidence").get(0);
            assertEquals(evidence.toJson().path("chunk_text"), forwarded.path("original").path("chunk_text"));
            assertEquals(evidence.toJson().path("metadata"), forwarded.path("original").path("metadata"));
            assertEquals(evidence.toJson().path("place_refs"), forwarded.path("annotations").path("place_refs"));
            assertTrue(forwarded.path("generatedSupplement").isEmpty());
            var answer = mapper.createObjectNode().put("message", place.name() + "을 찾았습니다.");
            answer.putArray("citations").addObject().put("placeId", place.id())
                    .put("evidenceId", forwarded.path("evidenceId").asText())
                    .put("sourceId", evidence.sourceId()).put("quote", existingQuote(record.path("case_id").asText(), place.id()));
            return LlmTurn.builder().content(answer.toString()).build();
        });
        var service = new ConversationService(
                llm,
                registry,
                new ConversationToolExecutor(registry, mapper),
                new ConversationAnswerRenderer(mapper),
                mapper,
                2,
                1,
                ConversationService.ToolFailurePolicy.STOP,
                new ConversationEvidencePreparation(List.of())
        );
        var request = mapper.treeToValue(record.path("api_request"), ConversationRequest.class);
        var response = service.respond("MOCK-owner", UUID.randomUUID(), request);
        Path captureDirectory = Path.of("build/search-contract-regression");
        Files.createDirectories(captureDirectory);
        Files.write(captureDirectory.resolve(record.path("case_id").asText() + ".mock-turns.jsonl"), capturedFrames);
        assertEquals(rawArguments, response.toolResults().get(0).arguments(), "The raw provider arguments must never be repaired");
        if (record.path("termination").asText().equals("TOOL_FAILED")) {
            assertEquals(ConversationResponse.Termination.TOOL_FAILED, response.termination());
            assertEquals("Search query required", response.toolResults().get(0).publicData().path("message").asText());
            verifyNoInteractions(searches);
            verify(llm, times(1)).chat(anyList(), anyList());
            return;
        }
        assertDoesNotThrow(() -> ToolSchemas.validate(tool.definition().parameters(), mapper.readTree(rawArguments)));
        assertEquals(ConversationResponse.Termination.COMPLETED, response.termination());
        assertEquals(ConversationResponse.MessageSource.LLM, response.messageSource());
        assertEquals(1, response.citations().size());
        assertTrue(response.citations().get(0).quote().length() < evidence.toJson().path("chunk_text").asText().length());
        assertEquals(evidence.toJson(), response.data().get(0).path("evidenceChunks").get(0));
        String expectedQuery = mapper.readTree(rawArguments).path("query").asText();
        verify(searches).search(argThat(criteria -> criteria.query().equals(expectedQuery)));
        verify(llm, times(2)).chat(anyList(), anyList());
    }

    private String existingQuote(String caseId, long placeId) throws Exception {
        for (String line : Files.readAllLines(Path.of("../../Evaluation/datasets/v1.4.0/generated/golden.jsonl"))) {
            JsonNode existing = mapper.readTree(line);
            if (!existing.path("case_id").asText().equals(caseId)) continue;
            for (JsonNode judgment : existing.path("place_judgments")) {
                if (judgment.path("place_id").asLong() != placeId) continue;
                for (JsonNode source : judgment.path("evidence")) {
                    if (source.path("field").asText().equals("description")) return source.path("quote").asText();
                }
            }
        }
        throw new IllegalStateException("Existing case has no description quote");
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "{}", "{\"query\":null}", "{\"query\":\" \"}", "{\"query\":\"\\u2003\"}", "{\"query\":\"x\",\"excludePlaceIds\":[]}",
            "{\"query\":\"x\",\"limit\":null}", "{\"query\":\"x\",\"limit\":0}", "{\"query\":\"x\",\"limit\":21}",
            "{\"query\":\"x\",\"exclude_place_ids\":[1,1.0]}", "{\"query\":\"x\",\"exclude_place_ids\":[1.5]}",
            "{\"query\":\"x\",\"city\":\" \"}",
            "{\"query\":\"x\",\"area\":{\"type\":\"CIRCLE\",\"center\":{\"lat\":91,\"lon\":0},\"radius_meters\":500}}",
            "{\"query\":\"x\",\"area\":{\"type\":\"CIRCLE\",\"center\":{\"lat\":0,\"lon\":0},\"radius_meters\":499}}"
    })
    void publishedContractAndResolverBothRejectInvalidArguments(String encoded) throws Exception {
        JsonNode arguments = mapper.readTree(encoded);
        assertThrows(IllegalArgumentException.class, () -> ToolSchemas.validate(SearchPlacesContract.parameters(), arguments));
        assertThrows(IllegalArgumentException.class, () -> resolver.resolve(new ConversationRequest("Do not guess query", null, List.of()), arguments));
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "{\"query\":\"x\"}",
            "{\"query\":\"x\",\"region\":null,\"city\":null,\"category\":null,\"exclude_place_ids\":null,\"area\":null}",
            "{\"query\":\"x\",\"limit\":1,\"exclude_place_ids\":[1,9223372036854775807]}",
            "{\"query\":\"x\",\"limit\":20,\"area\":{\"type\":\"CIRCLE\",\"center\":{\"lat\":-90,\"lon\":180},\"radius_meters\":10000}}"
    })
    void optionalFieldsAndBoundsHaveOnePublishedContract(String encoded) throws Exception {
        JsonNode arguments = mapper.readTree(encoded);
        assertDoesNotThrow(() -> ToolSchemas.validate(SearchPlacesContract.parameters(), arguments));
        var resolved = resolver.resolve(new ConversationRequest("x", null, List.of()), arguments);
        assertEquals(arguments.path("limit").asInt(10), resolved.criteria().limit());
        assertEquals(mapper.readTree("[\"query\"]"), SearchPlacesContract.parameters().path("required"));
        assertEquals(10, SearchPlacesContract.parameters().path("properties").path("limit").path("default").asInt());
    }

    @Test
    void exportedSchemaCannotBeMutatedToRelaxRuntimeValidation() throws Exception {
        var published = SearchPlacesContract.parameters();
        ((com.fasterxml.jackson.databind.node.ObjectNode) published).remove("required");
        assertThrows(IllegalArgumentException.class, () -> SearchPlacesContract.validate(mapper.readTree("{}")));
    }

    @Test
    void unicodeLengthUsesCodepointsInBothSchemaAndEffectiveCriteria() {
        String symbol = Character.toString(0x1F30F);
        JsonNode arguments = mapper.createObjectNode().put("query", symbol.repeat(2000)).put("city", symbol.repeat(200));
        var criteria = resolver.resolve(new ConversationRequest("x", null, List.of()), arguments).criteria();
        try (var factory = jakarta.validation.Validation.buildDefaultValidatorFactory()) {
            assertTrue(factory.getValidator().validate(criteria).isEmpty());
        }
        assertThrows(IllegalArgumentException.class, () -> SearchPlacesContract.validate(
                mapper.createObjectNode().put("query", symbol.repeat(2001))));
    }

    @Test
    void exportContractAndTechnicalCasesForAnIndependentOfflineJsonSchemaCheck() throws Exception {
        Path directory = Path.of("build/search-contract-regression");
        Files.createDirectories(directory);
        Files.writeString(directory.resolve("contract.json"), mapper.writerWithDefaultPrettyPrinter().writeValueAsString(SearchPlacesContract.parameters()));
        var matrix = mapper.createArrayNode();
        for (var method : getClass().getDeclaredMethods()) {
            var cases = method.getAnnotation(ValueSource.class);
            if (cases == null) continue;
            for (String encoded : cases.strings()) {
                JsonNode arguments = mapper.readTree(encoded);
                boolean accepted;
                try {
                    resolver.resolve(new ConversationRequest("Never infer query", null, List.of()), arguments);
                    accepted = true;
                } catch (IllegalArgumentException exception) {
                    accepted = false;
                }
                matrix.addObject().put("kind", "TECHNICAL_ARGUMENT_REGRESSION").put("server_accepted", accepted).set("arguments", arguments);
            }
        }
        for (String line : Files.readAllLines(LIVE.resolve("records-all-observed.jsonl"))) {
            JsonNode record = mapper.readTree(line);
            JsonNode arguments = mapper.readTree(record.path("tool_calls").get(0).path("function").path("arguments").asText());
            matrix.addObject().put("kind", "RECORDED_NATIVE_ARGUMENTS").put("case_id", record.path("case_id").asText())
                    .put("server_accepted", record.path("termination").asText().equals("COMPLETED")).set("arguments", arguments);
        }
        Files.writeString(directory.resolve("acceptance-matrix.json"), mapper.writerWithDefaultPrettyPrinter().writeValueAsString(matrix));
    }
}
