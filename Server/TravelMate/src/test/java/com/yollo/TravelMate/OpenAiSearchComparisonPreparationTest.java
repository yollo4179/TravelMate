package com.yollo.TravelMate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.UUID;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.LlmProvider;
import com.yollo.TravelMate.ai.llm.budget.LlmCallGuard;
import com.yollo.TravelMate.ai.llm.budget.TokenBudget;
import com.yollo.TravelMate.ai.llm.derived.OpenAiLlmClient;
import com.yollo.TravelMate.ai.llm.observation.ExecutionRecorder;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.service.ConversationAnswerRenderer;
import com.yollo.TravelMate.domain.conversation.service.ConversationService;
import com.yollo.TravelMate.domain.conversation.service.ConversationToolExecutor;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import com.yollo.TravelMate.domain.conversation.tool.PlaceSearchCriteriaResolver;
import com.yollo.TravelMate.domain.conversation.tool.SearchPlacesTool;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult;
import com.yollo.TravelMate.domain.place.data.result.SearchEvidenceChunk;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class OpenAiSearchComparisonPreparationTest {
    private static final String PROPOSED_MODEL = "gpt-5.4-mini-2026-03-17";
    private static final Path RUNS = Path.of("../../Evaluation/runs/contextual");
    private final JsonMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();

    @ParameterizedTest
    @ValueSource(strings = {
            "b-live-integration-v1",
            "qwen-gpu-two-case-retest-v1"
    })
    void nativeArgumentsPassThroughTheExistingOpenAiLoopWithoutRepair(String fixtureRun) throws Exception {
        JsonNode recorded = mapper.readTree(Files.readAllLines(
                RUNS.resolve(fixtureRun + "/20261102-01/raw/records-all-observed.jsonl")).get(0));
        String nativeArguments = recorded.path("tool_calls").get(0).path("function").path("arguments").asText();
        String expectedQuery = mapper.readTree(nativeArguments).path("query").asText();
        boolean recordedSuccess = recorded.path("termination").asText().equals("COMPLETED");
        var mockAnswer = mapper.createObjectNode();
        var searches = mock(PlaceSemanticSearchService.class);
        JsonNode originalResponse = mapper.readTree(RUNS.resolve(
                "b-live-integration-v1/20261102-01/raw/PLR-TM-palaces-01.response.json").toFile());
        JsonNode originalPlace = originalResponse.path("data").get(0);
        var place = mapper.treeToValue(mapper.createObjectNode()
                .put("id", originalPlace.path("placeId").asLong())
                .put("name", originalPlace.path("name").asText())
                .put("description", originalPlace.path("description").asText()), PlaceResult.class);
        var evidence = new SearchEvidenceChunk(originalPlace.path("evidenceChunks").get(0));
        when(searches.search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class)))
                .thenReturn(List.of(new PlaceSemanticSearchResult(place, 1f, List.of(evidence))));
        var tool = new SearchPlacesTool(searches, new PlaceSearchCriteriaResolver(), new ContextPlanPromptFactory(mapper), mapper);
        var registry = new ConversationToolRegistry(List.of(tool), "SEARCH_PLACES");
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        var limits = TokenBudget.Limits.builder()
                .provider(LlmProvider.OPENAI)
                .model(PROPOSED_MODEL)
                .contextTokens(8192)
                .outputReservation(1536)
                .modelOutputLimit(128000)
                .limitsModel(PROPOSED_MODEL)
                .limitsSource("MOCK preparation; proposed model's documented maximum, local cap 8192")
                .build();
        var client = new OpenAiLlmClient(
                builder.build(),
                "MOCK-NOT-A-KEY",
                limits,
                new LlmCallGuard(mapper, mock(ExecutionRecorder.class))
        );
        expectCount(server, 1000);
        var nativeCompletion = mapper.createObjectNode().put("status", "completed");
        nativeCompletion.putArray("output").addObject()
                .put("type", "function_call")
                .put("call_id", "mock-call-from-recording")
                .put("name", "search_places")
                .put("arguments", nativeArguments);
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andExpect(jsonPath("$.model").value(PROPOSED_MODEL))
                .andExpect(jsonPath("$.tools[0].strict").value(false))
                .andExpect(jsonPath("$.tools[0].parameters.additionalProperties").value(false))
                .andExpect(jsonPath("$.tools[0].parameters.properties.searchContext").doesNotExist())
                .andExpect(jsonPath("$.parallel_tool_calls").value(false))
                .andExpect(jsonPath("$.service_tier").value("default"))
                .andExpect(jsonPath("$.max_output_tokens").value(1536))
                .andExpect(request -> {
                    var encoded = ((org.springframework.mock.http.client.MockClientHttpRequest) request).getBodyAsString();
                    JsonNode wire = mapper.readTree(encoded);
                    assertTrue(wire.path("input").get(0).path("content").asText().contains("요청 봉투"));
                    assertEquals(recorded.path("api_request").path("searchContext"),
                            mapper.readTree(wire.path("input").get(1).path("content").asText()).path("searchContext"));
                })
                .andRespond(withSuccess(nativeCompletion.toString(), MediaType.APPLICATION_JSON));
        if (recordedSuccess) {
            // The final text is a preserved answer fixture, not newly measured model quality.
            mockAnswer.put("message", originalResponse.path("message").asText());
            mockAnswer.set("citations", originalResponse.path("citations").deepCopy());
            expectCount(server, 2000);
            server.expect(requestTo("https://mock.invalid/v1/responses"))
                    .andExpect(request -> {
                        var encoded = ((org.springframework.mock.http.client.MockClientHttpRequest) request).getBodyAsString();
                        JsonNode wire = mapper.readTree(encoded);
                        assertEquals(nativeArguments, wire.path("input").get(2).path("arguments").asText());
                        JsonNode feedback = mapper.readTree(wire.path("input").get(3).path("output").asText());
                        JsonNode selected = feedback.path("data").path("candidates").get(0).path("selectedEvidence").get(0);
                        assertEquals(evidence.toJson().path("chunk_text"), selected.path("original").path("chunk_text"));
                        assertEquals(evidence.toJson().path("metadata"), selected.path("original").path("metadata"));
                        assertEquals(evidence.toJson().path("place_refs"), selected.path("annotations").path("place_refs"));
                        assertTrue(selected.path("generatedSupplement").isEmpty());
                        // This mock provider must cite the ID in this request, not a previous run's random namespace.
                        ((com.fasterxml.jackson.databind.node.ObjectNode) mockAnswer.path("citations").get(0))
                                .put("evidenceId", selected.path("evidenceId").asText());
                    })
                    .andRespond(request -> {
                        var finalCompletion = mapper.createObjectNode().put("status", "completed");
                        finalCompletion.putArray("output").addObject().put("type", "message")
                                .putArray("content").addObject().put("type", "output_text").put("text", mockAnswer.toString());
                        return withSuccess(finalCompletion.toString(), MediaType.APPLICATION_JSON).createResponse(request);
                    });
        }
        var service = new ConversationService(
                client,
                registry,
                new ConversationToolExecutor(registry, mapper),
                new ConversationAnswerRenderer(mapper),
                mapper,
                2,
                1,
                ConversationService.ToolFailurePolicy.STOP
        );
        var response = service.respond("MOCK-owner", UUID.randomUUID(),
                mapper.treeToValue(recorded.path("api_request"), ConversationRequest.class));
        assertEquals(nativeArguments, response.toolResults().get(0).arguments());
        if (!recordedSuccess) {
            assertEquals(ConversationResponse.Termination.TOOL_FAILED, response.termination());
            assertEquals("Unknown tool argument: $.searchContext", response.toolResults().get(0).publicData().path("message").asText());
            verifyNoInteractions(searches);
        } else {
            assertEquals(ConversationResponse.Termination.COMPLETED, response.termination());
            assertEquals(ConversationResponse.MessageSource.LLM, response.messageSource());
            assertEquals(mapper.treeToValue(mockAnswer, ConversationAnswerRenderer.Answer.class).citations(), response.citations());
            assertEquals(evidence.toJson(), response.data().get(0).path("evidenceChunks").get(0));
            verify(searches).search(argThat(criteria -> criteria.query().equals(expectedQuery)));
        }
        server.verify();
    }

    private void expectCount(MockRestServiceServer server, int inputTokens) {
        server.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andExpect(jsonPath("$.model").value(PROPOSED_MODEL))
                .andExpect(jsonPath("$.tools[0].strict").value(false))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":" + inputTokens + "}", MediaType.APPLICATION_JSON));
    }
}
