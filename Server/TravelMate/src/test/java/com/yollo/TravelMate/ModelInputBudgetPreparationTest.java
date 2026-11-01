package com.yollo.TravelMate;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.OllamaLlmClient;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.ExpectedCount;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class ModelInputBudgetPreparationTest {
    private static final Path PREPARATION = Path.of("../../Evaluation/runs/contextual/model-evaluation-preparation-v1/20261101-01");
    private static final Path PREVIOUS = Path.of("../../Evaluation/runs/contextual/token-budget-observation-v1/20261101-01");
    private final JsonMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();
    private enum Scope { INITIAL_API_REQUEST, SAVED_MOCK_SEARCH_FOLLOWUP, FUTURE_TOOL_RESULTS, ASYNC_PLAN_REQUEST }
    private enum Status { PASS, EXCEEDED, UNVERIFIED }
    private record Label(String caseId, Scope scope) {}

    @Test
    void inspectExistingInputsWithRealSerializationAndCapturedMetadataWithoutInference() throws Exception {
        var connections = readLines(PREPARATION.resolve("case-connections.jsonl"));
        var metadata = mapper.readTree(PREPARATION.resolve("qwen-show.json").toFile());
        var builder = RestClient.builder().baseUrl("http://metadata-replay.invalid");
        var http = MockRestServiceServer.bindTo(builder).build();
        http.expect(ExpectedCount.times(connections.size() + 1), requestTo("http://metadata-replay.invalid/api/show"))
                .andRespond(withSuccess(metadata.toString(), MediaType.APPLICATION_JSON));
        var captureGuard = mock(LlmCallGuard.class);
        var current = new AtomicReference<Label>();
        List<JsonNode> budgets = new ArrayList<>();
        List<LlmMessage> initialMessages = new ArrayList<>();
        var exampleWire = new AtomicReference<JsonNode>();
        doAnswer(invocation -> {
            TokenBudget.Limits limits = invocation.getArgument(0);
            JsonNode wire = invocation.getArgument(1);
            Supplier<TokenBudget.Count> counter = invocation.getArgument(2);
            var label = current.get();
            var row = mapper.createObjectNode().put("case_id", label.caseId()).put("scope", label.scope().name())
                    .put("wire_sha256", LlmCallGuard.sha256(wire.toString())).put("inference_dispatched", false)
                    .put("wire_utf8_bytes", wire.toString().getBytes(StandardCharsets.UTF_8).length)
                    .put("context_tokens_configured", limits.contextTokens()).put("output_reservation", limits.outputReservation())
                    .put("evidence_quality", "REAL_METADATA_WITH_OFFLINE_NATIVE_REQUEST");
            try {
                var count = counter.get();
                long context = Math.min(limits.contextTokens(), count.nativeContextTokens());
                boolean fits = limits.outputReservation() <= context && count.inputTokens() <= context - limits.outputReservation();
                row.put("status", fits ? Status.PASS.name() : Status.EXCEEDED.name())
                        .put("effective_context_tokens", context)
                        .put("reserved_total_upper_bound", Math.addExact(count.inputTokens(), limits.outputReservation()));
                row.set("count", mapper.valueToTree(count));
            } catch (RuntimeException exception) {
                row.put("status", Status.UNVERIFIED.name()).put("reason", exception.getClass().getSimpleName());
            }
            if (exampleWire.get() == null) exampleWire.set(wire.deepCopy());
            budgets.add(row);
            // The production inference supplier is deliberately never invoked by this inspection.
            return LlmTurn.builder().content("{\"message\":\"준비용 모의 종료\",\"citations\":[]}").build();
        }).when(captureGuard).call(any(), any(), any(), any(), any(), any());
        var client = new OllamaLlmClient(builder.build(), "qwen3:8b", 8192, 1536, captureGuard);
        var planning = mock(ContextPlanningService.class);
        var prompts = new ContextPlanPromptFactory(mapper);
        var planningResults = new PlanningToolResults(planning, mapper);
        var registry = new ConversationToolRegistry(List.of(new SearchPlacesTool(planning, prompts, mapper),
                new GeneratePlanTool(planning, planningResults), new GetPlanningJobTool(planning, planningResults)));
        var recordingClient = mock(LlmClient.class);
        when(recordingClient.chat(anyList(), anyList())).thenAnswer(invocation -> {
            List<LlmMessage> messages = invocation.getArgument(0);
            if (initialMessages.isEmpty()) initialMessages.addAll(messages);
            return client.chat(messages, invocation.getArgument(1));
        });
        var conversation = new ConversationService(recordingClient, registry,
                new ConversationToolExecutor(registry, mapper), new ConversationAnswerRenderer(mapper), mapper, 6, 8);
        for (var connection : connections) {
            current.set(new Label(connection.path("case_id").asText(), Scope.INITIAL_API_REQUEST));
            var request = mapper.treeToValue(connection.path("minimal_api_request"), ConversationRequest.class);
            conversation.respond("offline-inspection", UUID.randomUUID(), request);
        }
        var previousEvents = readLines(PREVIOUS.resolve("events.jsonl"));
        var selected = previousEvents.stream().filter(event -> "TOOL_RESULT".equals(event.path("event").asText()))
                .findFirst().orElseThrow().path("payload");
        var nativeTool = selected.path("result");
        var toolCall = new LlmTurn.ToolCall(nativeTool.path("callId").asText(), nativeTool.path("name").asText(),
                nativeTool.path("arguments").asText());
        var originalRequest = mapper.createObjectNode().put("message", initialMessages.get(1).content() == null ? "" :
                mapper.readTree(initialMessages.get(1).content()).path("message").asText());
        originalRequest.set("planningRequest", selected.path("modelData").path("request"));
        var feedback = mapper.createObjectNode().put("type", nativeTool.path("type").asText());
        feedback.set("data", selected.path("modelData"));
        var followup = List.of(initialMessages.get(0), LlmMessage.text(LlmMessage.Role.USER, originalRequest.toString()),
                LlmMessage.assistant(LlmTurn.builder().toolCalls(List.of(toolCall)).build()),
                LlmMessage.tool(toolCall, feedback.toString()));
        current.set(new Label(connections.get(0).path("case_id").asText(), Scope.SAVED_MOCK_SEARCH_FOLLOWUP));
        client.chat(followup, registry.definitions());
        for (var scope : List.of(Scope.FUTURE_TOOL_RESULTS, Scope.ASYNC_PLAN_REQUEST)) {
            budgets.add(mapper.createObjectNode().put("scope", scope.name()).put("status", Status.UNVERIFIED.name())
                    .put("reason", "No captured native prompt/results for a future live run; search and generation were not executed")
                    .put("inference_dispatched", false));
        }
        assertEquals(connections.size() + 3, budgets.size());
        assertTrue(budgets.stream().noneMatch(row -> row.path("inference_dispatched").asBoolean()));
        assertTrue(budgets.stream().filter(row -> row.has("count")).allMatch(row ->
                "CONSERVATIVE_BOUND".equals(row.path("count").path("quality").asText())));
        verifyNoInteractions(planning);
        http.verify();
        var output = Path.of("build/pre-evaluation");
        Files.createDirectories(output);
        Files.writeString(output.resolve("qwen-budgets.jsonl"), budgets.stream().map(JsonNode::toString)
                .collect(java.util.stream.Collectors.joining("\n", "", "\n")), StandardCharsets.UTF_8);
        Files.writeString(output.resolve("initial-wire-example.json"), exampleWire.get().toPrettyString() + "\n", StandardCharsets.UTF_8);
    }

    private List<JsonNode> readLines(Path source) throws Exception {
        List<JsonNode> rows = new ArrayList<>();
        for (String line : Files.readAllLines(source, StandardCharsets.UTF_8)) {
            if (!line.isBlank()) rows.add(mapper.readTree(line));
        }
        return rows;
    }
}
