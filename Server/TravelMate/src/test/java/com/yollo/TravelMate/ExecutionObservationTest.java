package com.yollo.TravelMate;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.OpenAiLlmClient;
import com.yollo.TravelMate.ai.llm.observation.*;
import com.yollo.TravelMate.config.observability.ExecutionObservationFilter;
import com.yollo.TravelMate.domain.conversation.controller.ConversationController;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.place.data.result.*;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import com.yollo.TravelMate.domain.user.entity.User;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.TestingAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.method.annotation.AuthenticationPrincipalArgumentResolver;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.client.RestClient;
import static com.yollo.TravelMate.SearchEvidenceFixtures.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class ExecutionObservationTest {
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();

    @Test
    void actualFilterAndLoopCaptureBudgetRejectionAfterUntruncatedToolEvidence() throws Exception {
        JsonNode binding;
        try (var stream = getClass().getResourceAsStream("/token-budget/existing-case-binding.json")) {
            binding = mapper.readTree(java.util.Objects.requireNonNull(stream));
        }
        List<JsonNode> events = new CopyOnWriteArrayList<>();
        var recorder = mock(ExecutionRecorder.class);
        doAnswer(invocation -> { events.add(invocation.<JsonNode>getArgument(0).deepCopy()); return null; })
                .when(recorder).write(any());
        var guard = new LlmCallGuard(mapper, recorder);
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var http = MockRestServiceServer.bindTo(builder).build();
        var client = new OpenAiLlmClient(builder.build(), "test-key", TokenBudget.Limits.builder()
                .provider(LlmProvider.OPENAI).model("gpt-mock").contextTokens(10000).outputReservation(1536)
                .modelOutputLimit(2000).limitsModel("gpt-mock").limitsSource("MOCK limits").build(), guard);
        var callResponse = mapper.createObjectNode().put("status", "completed");
        callResponse.putObject("usage").put("input_tokens", 100).put("output_tokens", 20);
        callResponse.putArray("output").addObject().put("type", "function_call").put("id", "fc1")
                .put("call_id", "search1").put("name", "search_places")
                .put("arguments", mapper.writeValueAsString(Map.of("query", binding.path("query").asText(), "limit", 5)));
        http.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":100}", MediaType.APPLICATION_JSON));
        http.expect(requestTo("https://mock.invalid/v1/responses"))
                .andRespond(withSuccess(callResponse.toString(), MediaType.APPLICATION_JSON));
        http.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andExpect(request -> {
                    var actual = (org.springframework.mock.http.client.MockClientHttpRequest) request;
                    JsonNode counted = mapper.readTree(actual.getBodyAsString(StandardCharsets.UTF_8));
                    JsonNode toolResult = mapper.readTree(counted.path("input").get(3).path("output").asText());
                    var evidence = toolResult.path("data").path("candidates").get(0).path("selectedEvidence");
                    assertEquals(ORIGINAL, evidence.get(0).path("original").path("chunk_text").asText());
                    assertEquals(BLOCK, evidence.get(1).path("original").path("chunk_text").asText());
                    assertTrue(evidence.get(0).has("generatedSupplement"));
                })
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":100000}", MediaType.APPLICATION_JSON));
        var planning = mock(ContextPlanningService.class);
        var place = mapper.readValue("""
                {"id":101,"name":"모의 A공원","category":"카페","latitude":35.8395,"longitude":129.212}
                """, PlaceResult.class);
        var result = new PlaceSemanticSearchResult(place, 0.8f, List.of(
                new SearchEvidenceChunk(chunk(mapper, ORIGINAL, WALK)),
                new SearchEvidenceChunk(chunk(mapper, BLOCK, BLOCK))
        ));
        when(planning.search(any(), anyString(), anyInt())).thenReturn(List.of(result));
        var factory = new ContextPlanPromptFactory(mapper);
        var jobResults = new PlanningToolResults(planning, mapper);
        var registry = new ConversationToolRegistry(List.of(
                new SearchPlacesTool(planning, factory, mapper),
                new GeneratePlanTool(planning, jobResults), new GetPlanningJobTool(planning, jobResults)));
        var service = new ConversationService(
                new StrategyLlmClient(List.of(client), LlmProvider.OPENAI),
                registry,
                new ConversationToolExecutor(registry, mapper),
                new ConversationAnswerRenderer(mapper),
                mapper,
                6,
                8
        );
        var mvc = MockMvcBuilders.standaloneSetup(new ConversationController(service))
                .setCustomArgumentResolvers(new AuthenticationPrincipalArgumentResolver())
                .addFilters(new ExecutionObservationFilter(recorder, mapper, ObservationContext.Mode.MOCK)).build();
        var request = mapper.createObjectNode().put("message", binding.path("query").asText());
        request.set("planningRequest", mapper.readTree(PlanContextContractTest.REQUEST));
        SecurityContextHolder.getContext().setAuthentication(new TestingAuthenticationToken(User.builder().uid("owner").build(), null));
        String response;
        try {
            response = mvc.perform(post("/api/v1/conversation/turns")
                            .header("Idempotency-Key", UUID.randomUUID())
                            .header("X-Conversation-Id", binding.path("conversationId").asText())
                            .header("X-Evaluation-Case-Id", binding.path("case_id").asText())
                            .header("X-Evaluation-Input-Sha256", binding.path("input_sha256").asText())
                            .characterEncoding(StandardCharsets.UTF_8)
                            .contentType(MediaType.APPLICATION_JSON).content(request.toString()))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.type").value("PLACES"))
                    .andExpect(jsonPath("$.termination").value("BUDGET_REJECTED"))
                    .andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8);
        } finally {
            SecurityContextHolder.clearContext();
        }
        assertNull(ObservationContext.capture());
        var toolEvent = events.stream().filter(event -> "TOOL_RESULT".equals(event.path("event").asText()))
                .findFirst().orElseThrow();
        JsonNode expectedRequest = mapper.valueToTree(mapper.readValue(PlanContextContractTest.REQUEST, GeneratePlanRequest.class));
        assertEquals(expectedRequest.path("context").path("preferences"),
                toolEvent.path("payload").path("modelData").path("request").path("context").path("preferences"));
        assertTrue(events.stream().allMatch(event -> event.path("mode").asText().equals("MOCK")));
        long rejected = events.stream().filter(event -> event.path("payload").path("status").asText().equals("BUDGET_REJECTED")).count();
        assertEquals(1, rejected);
        http.verify();
        Path directory = Path.of("build/mock-execution");
        Files.createDirectories(directory);
        Files.writeString(directory.resolve("events.jsonl"), events.stream().map(JsonNode::toString)
                .collect(java.util.stream.Collectors.joining("\n", "", "\n")), StandardCharsets.UTF_8);
        var exportedBinding = mapper.createObjectNode().put("case_id", binding.path("case_id").asText())
                .put("input_sha256", binding.path("input_sha256").asText())
                .put("request_id", mapper.readTree(response).path("requestId").asText());
        exportedBinding.set("api_request", request);
        Files.writeString(directory.resolve("bindings.jsonl"), exportedBinding + "\n", StandardCharsets.UTF_8);
    }
}
