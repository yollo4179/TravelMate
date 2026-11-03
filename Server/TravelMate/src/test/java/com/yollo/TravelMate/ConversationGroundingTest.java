package com.yollo.TravelMate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.OpenAiLlmClient;
import com.yollo.TravelMate.ai.llm.derived.OpenAiToolContracts;
import com.yollo.TravelMate.ai.llm.observation.*;
import com.yollo.TravelMate.domain.conversation.data.*;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.*;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest;
import com.yollo.TravelMate.domain.place.data.result.*;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.core.env.MapPropertySource;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class ConversationGroundingTest {
    private static final Path ARCHIVE = Path.of("../../Evaluation/runs/contextual/openai-strict-search-two-case-v1/20261103-01/raw");
    private static final String MODEL = "gpt-5.4-mini-2026-03-17";
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();
    private final PlaceSemanticSearchService searches = mock(PlaceSemanticSearchService.class);
    private final ContextPlanningService planning = mock(ContextPlanningService.class);
    @TempDir
    Path temporary;

    private record PreservedCase(String id, ConversationRequest request, JsonNode reply, JsonNode modelData, List<PlaceSemanticSearchResult> results) {}

    static Stream<String> existingCases() {
        return Stream.of("PLR-TM-palaces-01", "PLR-TM-palaces-03");
    }

    @ParameterizedTest
    @MethodSource("existingCases")
    void productionWiringPreparesOriginalsBeforeOneGroundedAnswerWithAllRegisteredTools(String caseId) throws Exception {
        var preserved = preserved(caseId);
        var llm = mock(LlmClient.class);
        when(searches.search(any(PlaceSearchRequest.class))).thenReturn(preserved.results());
        List<JsonNode> events = new ArrayList<>();
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            List<LlmMessage> messages = invocation.getArgument(0);
            List<LlmTurn.ToolDefinition> definitions = invocation.getArgument(1);
            assertEquals(List.of("generate_plan", "get_planning_job", "search_places"),
                    definitions.stream().map(LlmTurn.ToolDefinition::name).toList());
            verify(searches).search(argThat(criteria -> criteria.query().equals(preserved.request().message())
                    && criteria.region().equals(preserved.request().searchContext().region())
                    && java.util.Objects.equals(criteria.city(), preserved.request().searchContext().city())
                    && criteria.category() == null));
            var envelope = envelope(messages);
            assertEquals(preserved.request().message(), envelope.path("message").asText());
            assertEquals(mapper.valueToTree(preserved.request().searchContext()), envelope.path("searchContext"));
            assertTrue(envelope.path("planningRequest").isNull());
            assertEquals(ConversationEvidencePreparation.State.READY.name(), envelope.path("serverEvidence").path("state").asText());
            assertOriginals(preserved, envelope.path("serverEvidence").path("data"));
            assertTrue(messages.stream().noneMatch(message -> message.role() == LlmMessage.Role.TOOL));
            var captured = mapper.createObjectNode().put("mode", "MOCK").put("caseId", caseId);
            captured.set("messages", mapper.valueToTree(messages));
            captured.set("tools", mapper.valueToTree(definitions));
            writeArtifact(caseId + ".first-input.json", captured);
            return LlmTurn.builder().content(answer(preserved, envelope.path("serverEvidence").path("data")).toString()).build();
        });
        var observation = ObservationContext.Context.builder().mode(ObservationContext.Mode.MOCK)
                .phase(ObservationContext.Phase.REQUEST).caseId(caseId).sink(event -> events.add(event.deepCopy())).build();
        try (var context = context(llm, 1, 1); var scope = ObservationContext.open(observation)) {
            var response = context.getBean(ConversationService.class).respond("owner", UUID.randomUUID(), preserved.request());
            assertEquals(Termination.COMPLETED, response.termination());
            assertEquals(ResultType.PLACES, response.type());
            assertEquals(MessageSource.LLM, response.messageSource());
            assertEquals(1, response.modelTurns());
            assertTrue(response.toolResults().isEmpty(), "Preparation must not invent a model tool call");
            assertEquals(preserved.reply().path("data"), mapper.readTree(response.data().toString()));
            assertEquals(preserved.reply().path("message").asText(), response.message());
            assertFalse(response.citations().isEmpty());
            assertEquals("EVIDENCE_PREPARATION", events.get(0).path("event").asText());
            var ordering = inOrder(searches, llm);
            ordering.verify(searches).search(any(PlaceSearchRequest.class));
            ordering.verify(llm).chat(anyList(), anyList());
            verifyNoMoreInteractions(llm);
            verifyNoInteractions(planning);
            writeArtifact(caseId + ".response.json", mapper.valueToTree(response));
            writeArtifact(caseId + ".verification.json", mapper.createObjectNode()
                    .put("mode", "MOCK").put("modelCalls", 1).put("preparations", 1).put("afterModelSearches", 0)
                    .put("firstInputContainsPreservedOriginals", true).put("citationsValidated", true)
                    .put("answerSource", "preserved answer fixture with current evidence IDs")
                    .put("realModelQualityMeasured", false).put("paidCalls", 0));
        }
    }

    @ParameterizedTest
    @MethodSource("existingCases")
    void firstNativeCountAndInferenceRequestsBothContainThePreparedOriginals(String caseId) throws Exception {
        var preserved = preserved(caseId);
        when(searches.search(any(PlaceSearchRequest.class))).thenReturn(preserved.results());
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var http = MockRestServiceServer.bindTo(builder).build();
        var client = client(builder);
        http.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andExpect(request -> assertNativeInput(preserved, mapper.readTree(
                        ((org.springframework.mock.http.client.MockClientHttpRequest) request).getBodyAsString())))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":6000}", MediaType.APPLICATION_JSON));
        http.expect(requestTo("https://mock.invalid/v1/responses"))
                .andRespond(request -> {
                    var wire = mapper.readTree(((org.springframework.mock.http.client.MockClientHttpRequest) request).getBodyAsString());
                    assertNativeInput(preserved, wire);
                    writeArtifact(caseId + ".native-first-request.json", wire);
                    var envelope = nativeEnvelope(wire);
                    var completion = mapper.createObjectNode().put("status", "completed").put("model", MODEL).put("service_tier", "default");
                    completion.putObject("usage").put("input_tokens", 6000).put("output_tokens", 100);
                    completion.putArray("output").addObject().put("type", "message")
                            .putArray("content").addObject().put("type", "output_text")
                            .put("text", answer(preserved, envelope.path("serverEvidence").path("data")).toString());
                    return withSuccess(completion.toString(), MediaType.APPLICATION_JSON).createResponse(request);
                });
        try (var context = context(client, 1, 1); var scope = observation(preserved)) {
            var response = context.getBean(ConversationService.class).respond("owner", UUID.randomUUID(), preserved.request());
            assertEquals(Termination.COMPLETED, response.termination());
            assertEquals(MessageSource.LLM, response.messageSource());
            assertEquals(1, response.modelTurns());
            assertFalse(response.citations().isEmpty());
            http.verify();
        }
    }

    @Test
    void preparationFailureStopsBeforeModelAndRemainsDistinctFromAnEmptySearch() throws Exception {
        var preserved = preserved("PLR-TM-palaces-01");
        var llm = mock(LlmClient.class);
        when(searches.search(any(PlaceSearchRequest.class))).thenThrow(new IllegalStateException("offline search failure"));
        try (var context = context(llm, 1, 1)) {
            var response = context.getBean(ConversationService.class).respond("owner", UUID.randomUUID(), preserved.request());
            assertEquals(Termination.TOOL_FAILED, response.termination());
            assertEquals(ResultType.ERROR, response.type());
            assertEquals("EVIDENCE_PREPARATION_FAILED", response.data().path("code").asText());
            assertEquals(0, response.modelTurns());
            verifyNoInteractions(llm);
        }
    }

    @Test
    void fullPreparedEvidenceStillPassesThroughTheExistingTokenGuardBeforeInference() throws Exception {
        var preserved = preserved("PLR-TM-palaces-01");
        when(searches.search(any(PlaceSearchRequest.class))).thenReturn(preserved.results());
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var http = MockRestServiceServer.bindTo(builder).build();
        var client = client(builder);
        http.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andExpect(request -> assertNativeInput(preserved, mapper.readTree(
                        ((org.springframework.mock.http.client.MockClientHttpRequest) request).getBodyAsString())))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":100000}", MediaType.APPLICATION_JSON));
        try (var context = context(client, 1, 1); var scope = observation(preserved)) {
            var response = context.getBean(ConversationService.class).respond("owner", UUID.randomUUID(), preserved.request());
            assertEquals(Termination.BUDGET_REJECTED, response.termination());
            assertEquals(preserved.reply().path("data"), mapper.readTree(response.data().toString()));
            assertTrue(response.citations().isEmpty());
            http.verify();
        }
    }

    @Test
    void directClarificationDoesNotExposeUnrelatedPreparedPlacesOrRunAnAction() throws Exception {
        var preserved = preserved("PLR-TM-palaces-01");
        var llm = mock(LlmClient.class);
        when(searches.search(any(PlaceSearchRequest.class))).thenReturn(preserved.results());
        when(llm.chat(anyList(), anyList())).thenReturn(LlmTurn.builder()
                .content("{\"message\":\"추가로 어떤 조건을 원하시나요?\",\"citations\":[]}").build());
        try (var context = context(llm, 1, 1)) {
            var response = context.getBean(ConversationService.class).respond("owner", UUID.randomUUID(), preserved.request());
            assertEquals(ResultType.TEXT, response.type());
            assertTrue(response.data().isNull());
            assertEquals(MessageSource.LLM, response.messageSource());
            verify(llm).chat(anyList(), anyList());
            verifyNoInteractions(planning);
        }
    }

    @Test
    void theSameGroundedModelCanChooseAStateToolWithoutPretendingItAlreadyRan() throws Exception {
        var preserved = preserved("PLR-TM-palaces-03");
        var llm = mock(LlmClient.class);
        var jobId = UUID.randomUUID();
        when(searches.search(any(PlaceSearchRequest.class))).thenReturn(preserved.results());
        when(planning.job(jobId, "owner")).thenReturn(new com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.Job(
                jobId,
                com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus.RUNNING,
                "/api/v1/planning-jobs/" + jobId,
                null,
                null
        ));
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            verifyNoInteractions(planning);
            assertOriginals(preserved, envelope(invocation.getArgument(0)).path("serverEvidence").path("data"));
            return LlmTurn.builder().toolCalls(List.of(new LlmTurn.ToolCall(
                    "job-status",
                    "get_planning_job",
                    mapper.createObjectNode().put("job_id", jobId.toString()).toString()
            ))).build();
        });
        try (var context = context(llm, 1, 2)) {
            var response = context.getBean(ConversationService.class).respond("owner", UUID.randomUUID(), preserved.request());
            assertEquals(Termination.COMPLETED, response.termination());
            assertEquals(ResultType.PLANNING_JOB, response.type());
            assertEquals("RUNNING", response.data().path("status").asText());
            assertTrue(response.message().contains("아직 완성되지 않았습니다"));
            verify(planning).job(jobId, "owner");
            verify(llm).chat(anyList(), anyList());
        }
    }

    @Test
    void explicitReassessmentCanConsumeANewToolResultInTheSameModelConversation() throws Exception {
        var preserved = preserved("PLR-TM-palaces-03");
        var llm = mock(LlmClient.class);
        var oldArguments = preserved.reply().path("toolResults").get(0).path("arguments").asText();
        when(searches.search(any(PlaceSearchRequest.class))).thenReturn(preserved.results());
        var turns = new java.util.concurrent.atomic.AtomicInteger();
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            List<LlmMessage> messages = invocation.getArgument(0);
            if (turns.getAndIncrement() == 0) {
                assertOriginals(preserved, envelope(messages).path("serverEvidence").path("data"));
                return LlmTurn.builder().content("{\"afterTool\":\"REASSESS\"}")
                        .toolCalls(List.of(new LlmTurn.ToolCall("additional-search", "search_places", oldArguments))).build();
            }
            var feedback = mapper.readTree(messages.get(messages.size() - 1).content()).path("data");
            assertOriginals(preserved, feedback);
            return LlmTurn.builder().content(answer(preserved, feedback).toString()).build();
        });
        try (var context = context(llm, 2, 2)) {
            var response = context.getBean(ConversationService.class).respond("owner", UUID.randomUUID(), preserved.request());
            assertEquals(Termination.COMPLETED, response.termination());
            assertEquals(2, response.modelTurns());
            assertEquals(1, response.toolResults().size());
            assertFalse(response.citations().isEmpty());
            verify(searches, times(2)).search(any(PlaceSearchRequest.class));
            verify(llm, times(2)).chat(anyList(), anyList());
        }
    }

    @Test
    void inventedCitationsCannotBecomeAcceptedFirstTurnGroundedAnswers() throws Exception {
        var preserved = preserved("PLR-TM-palaces-01");
        var llm = mock(LlmClient.class);
        when(searches.search(any(PlaceSearchRequest.class))).thenReturn(preserved.results());
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            var reply = answer(preserved, envelope(invocation.getArgument(0)).path("serverEvidence").path("data"));
            ((ObjectNode) reply.path("citations").get(0)).put("sourceId", "invented-source");
            return LlmTurn.builder().content(reply.toString()).build();
        });
        try (var context = context(llm, 1, 1)) {
            var response = context.getBean(ConversationService.class).respond("owner", UUID.randomUUID(), preserved.request());
            assertEquals(Termination.INVALID_RESPONSE, response.termination());
            assertTrue(response.citations().isEmpty());
            assertEquals(ResultType.PLACES, response.type());
            assertEquals(MessageSource.SERVER_FALLBACK, response.messageSource());
            verify(llm).chat(anyList(), anyList());
        }
    }

    @Test
    void anActuallyEmptyPreparationCanBeExplainedOnceWithoutBeingAFailure() throws Exception {
        var preserved = preserved("PLR-TM-palaces-01");
        var llm = mock(LlmClient.class);
        when(searches.search(any(PlaceSearchRequest.class))).thenReturn(List.of());
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            var evidence = envelope(invocation.getArgument(0)).path("serverEvidence");
            assertEquals(ConversationEvidencePreparation.State.EMPTY.name(), evidence.path("state").asText());
            assertTrue(evidence.path("data").path("candidates").isEmpty());
            return LlmTurn.builder().content("{\"message\":\"이번 검색에서 확인된 장소 근거가 없습니다.\",\"citations\":[]}").build();
        });
        try (var context = context(llm, 1, 1)) {
            var response = context.getBean(ConversationService.class).respond("owner", UUID.randomUUID(), preserved.request());
            assertEquals(Termination.COMPLETED, response.termination());
            assertEquals(MessageSource.LLM, response.messageSource());
            verify(llm).chat(anyList(), anyList());
        }
    }

    private OpenAiLlmClient client(RestClient.Builder builder) throws IOException {
        var limits = TokenBudget.Limits.builder().provider(LlmProvider.OPENAI).model(MODEL)
                .contextTokens(8192).outputReservation(1536).modelOutputLimit(16384)
                .limitsModel(MODEL).limitsSource("MOCK limits; network replaced by MockRestServiceServer").build();
        var policy = mapper.readTree(ARCHIVE.getParent().resolve("policy/approved-inference-policy.json").toFile());
        var policyPath = temporary.resolve("mock-policy-" + UUID.randomUUID() + ".json");
        ((ObjectNode) policy).put("ledgerFile", "mock-reservations-" + UUID.randomUUID() + ".jsonl");
        mapper.writeValue(policyPath.toFile(), policy);
        return new OpenAiLlmClient(
                builder.build(),
                "MOCK-NOT-A-KEY",
                limits,
                new LlmCallGuard(mapper, mock(ExecutionRecorder.class)),
                OpenAiToolContracts.Mode.STRICT_SEARCH_V1,
                new OpenAiBatchBudget(policyPath.toString())
        );
    }

    private ObservationContext.Scope observation(PreservedCase preserved) throws IOException {
        var original = mapper.readTree(ARCHIVE.resolve(preserved.id() + ".request.json").toFile());
        return ObservationContext.open(ObservationContext.Context.builder()
                .requestId(UUID.randomUUID().toString())
                .caseId(preserved.id())
                .inputSha256(original.path("input_sha256").asText())
                .mode(ObservationContext.Mode.MOCK)
                .phase(ObservationContext.Phase.REQUEST)
                .sink(event -> {})
                .build());
    }

    private AnnotationConfigApplicationContext context(LlmClient client, int turns, int tools) {
        var context = new AnnotationConfigApplicationContext();
        context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("offline-bounds", Map.of(
                "travelmate.conversation.max-model-turns", turns,
                "travelmate.conversation.max-tool-calls", tools
        )));
        context.registerBean(ObjectMapper.class, () -> mapper);
        context.registerBean(LlmClient.class, () -> client);
        context.registerBean(PlaceSemanticSearchService.class, () -> searches);
        context.registerBean(ContextPlanningService.class, () -> planning);
        context.register(
                PlaceSearchCriteriaResolver.class,
                ContextPlanPromptFactory.class,
                SearchPlacesTool.class,
                PlanningToolResults.class,
                GeneratePlanTool.class,
                GetPlanningJobTool.class,
                ConversationToolRegistry.class,
                ConversationToolExecutor.class,
                ConversationAnswerRenderer.class,
                PlaceConversationEvidence.class,
                ConversationEvidencePreparation.class,
                ConversationService.class
        );
        context.refresh();
        // Lifecycle callbacks on the mock are not user-requested planning actions.
        clearInvocations(planning);
        return context;
    }

    private PreservedCase preserved(String caseId) throws Exception {
        var request = mapper.readTree(ARCHIVE.resolve(caseId + ".request.json").toFile());
        var reply = mapper.readTree(ARCHIVE.resolve(caseId + ".response.json").toFile());
        List<PlaceSemanticSearchResult> results = new ArrayList<>();
        for (var stored : reply.path("data")) {
            var place = mapper.createObjectNode().set("id", stored.get("placeId"));
            for (var field : List.of("name", "description", "region", "city", "category", "latitude", "longitude", "tourContentId", "imageUrl", "homepageUrl")) {
                ((ObjectNode) place).set(field, stored.get(field));
            }
            ((ObjectNode) place).set("similarity", stored.get("semanticScore"));
            results.add(new PlaceSemanticSearchResult(
                    mapper.treeToValue(place, PlaceResult.class),
                    stored.path("rerankScore").isNull() ? null : stored.path("rerankScore").floatValue(),
                    SearchEvidenceChunk.parse(stored.path("evidenceChunks"))
            ));
        }
        String followup = caseId.endsWith("01") ? "04-inference.request.json" : "08-inference.request.json";
        var wire = mapper.readTree(ARCHIVE.resolve(followup).toFile());
        var feedback = elements(wire.path("input")).filter(item -> "function_call_output".equals(item.path("type").asText()))
                .findFirst().orElseThrow();
        var modelData = mapper.readTree(feedback.path("output").asText()).path("data");
        return new PreservedCase(caseId, mapper.treeToValue(request.path("api_request"), ConversationRequest.class), reply, modelData, results);
    }

    private void assertNativeInput(PreservedCase preserved, JsonNode wire) throws IOException {
        assertEquals(MODEL, wire.path("model").asText());
        assertEquals(3, wire.path("tools").size());
        wire.path("tools").forEach(tool -> assertTrue(tool.path("strict").asBoolean()));
        assertOriginals(preserved, nativeEnvelope(wire).path("serverEvidence").path("data"));
    }

    private JsonNode nativeEnvelope(JsonNode wire) throws IOException {
        var user = elements(wire.path("input")).filter(item -> "user".equals(item.path("role").asText()))
                .reduce((earlier, later) -> later).orElseThrow();
        return mapper.readTree(user.path("content").asText());
    }

    private JsonNode envelope(List<LlmMessage> messages) throws IOException {
        return mapper.readTree(messages.stream().filter(message -> message.role() == LlmMessage.Role.USER)
                .reduce((earlier, later) -> later).orElseThrow().content());
    }

    private Stream<JsonNode> elements(JsonNode array) {
        return java.util.stream.StreamSupport.stream(array.spliterator(), false);
    }

    private void assertOriginals(PreservedCase preserved, JsonNode actual) {
        var expected = preserved.modelData().path("candidates");
        assertEquals(expected.size(), actual.path("candidates").size());
        for (int placeIndex = 0; placeIndex < expected.size(); placeIndex++) {
            var expectedEvidence = expected.get(placeIndex).path("selectedEvidence");
            var actualEvidence = actual.path("candidates").get(placeIndex).path("selectedEvidence");
            assertEquals(expectedEvidence.size(), actualEvidence.size());
            for (int evidenceIndex = 0; evidenceIndex < expectedEvidence.size(); evidenceIndex++) {
                for (var field : List.of("original", "annotations", "generatedSupplement", "retrieval")) {
                    assertEquals(expectedEvidence.get(evidenceIndex).get(field), actualEvidence.get(evidenceIndex).get(field));
                }
            }
        }
    }

    private ObjectNode answer(PreservedCase preserved, JsonNode grounding) {
        var answer = mapper.createObjectNode().set("message", preserved.reply().get("message"));
        var citations = ((ObjectNode) answer).putArray("citations");
        for (var saved : preserved.reply().path("citations")) {
            var candidate = elements(grounding.path("candidates"))
                    .filter(place -> place.path("placeId").asLong() == saved.path("placeId").asLong()).findFirst().orElseThrow();
            var evidence = elements(candidate.path("selectedEvidence"))
                    .filter(item -> item.path("original").path("source_id").equals(saved.path("sourceId"))).findFirst().orElseThrow();
            var citation = saved.deepCopy();
            ((ObjectNode) citation).set("evidenceId", evidence.get("evidenceId"));
            citations.add(citation);
        }
        return (ObjectNode) answer;
    }

    private void writeArtifact(String name, JsonNode artifact) throws IOException {
        var directory = Path.of("build/conversation-grounding-offline");
        Files.createDirectories(directory);
        mapper.writerWithDefaultPrettyPrinter().writeValue(directory.resolve(name).toFile(), artifact);
    }
}
