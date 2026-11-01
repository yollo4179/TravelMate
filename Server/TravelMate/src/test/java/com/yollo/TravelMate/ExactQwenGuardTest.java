package com.yollo.TravelMate;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.OllamaLlmClient;
import com.yollo.TravelMate.ai.llm.observation.*;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class ExactQwenGuardTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private static final Path SHOW = Path.of("../../Evaluation/runs/contextual/model-evaluation-preparation-v1/20261101-01/qwen-show.json");

    private void metadata(MockRestServiceServer server) throws Exception {
        server.expect(requestTo("http://mock.invalid/api/show"))
                .andRespond(withSuccess(mapper.readTree(SHOW.toFile()).toString(), MediaType.APPLICATION_JSON));
        server.expect(requestTo("http://mock.invalid/api/version"))
                .andRespond(withSuccess("{\"version\":\"0.40.13\"}", MediaType.APPLICATION_JSON));
        server.expect(requestTo("http://mock.invalid/api/tags"))
                .andRespond(withSuccess("{\"models\":[]}", MediaType.APPLICATION_JSON));
    }

    private JsonNode counted(JsonNode envelope, long tokens) {
        return mapper.createObjectNode().put("inputTokens", tokens).put("quality", "EXACT_LOCAL_CROSSCHECKED")
                .put("wireSha256", LlmCallGuard.sha256(envelope.path("wire").asText()))
                .put("templateSha256", "ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4")
                .put("modelDigest", "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41")
                .put("serverVersion", "0.40.13").put("nativeContextTokens", 40960);
    }

    @Test
    void everyCallCountsTheCompleteAccumulatedWireAndReservationBeforeDispatch() throws Exception {
        var builder = RestClient.builder().baseUrl("http://mock.invalid");
        var http = MockRestServiceServer.bindTo(builder).build();
        metadata(http);
        http.expect(requestTo("http://mock.invalid/api/chat")).andRespond(withSuccess("""
                {"done":true,"done_reason":"stop","message":{"role":"assistant","content":"説明"}}
                """, MediaType.APPLICATION_JSON));
        metadata(http);
        var process = mock(ExactQwenProcess.class);
        AtomicInteger counts = new AtomicInteger();
        when(process.count(any())).thenAnswer(invocation -> {
            JsonNode envelope = invocation.getArgument(0);
            JsonNode wire = mapper.readTree(envelope.path("wire").asText());
            assertEquals(8192, wire.path("options").path("num_ctx").asInt());
            assertEquals(1536, wire.path("options").path("num_predict").asInt());
            if (counts.incrementAndGet() == 1) return counted(envelope, 850);
            assertEquals(4, wire.path("messages").size());
            assertEquals("과거에는 통행할 수 없었다. 공사 조건.", wire.path("messages").get(3).path("content").asText());
            assertTrue(wire.has("tools"));
            return counted(envelope, 6657); // one token beyond 8192 - 1536
        });
        List<JsonNode> events = new ArrayList<>();
        var client = new OllamaLlmClient(builder.build(), "qwen3:8b", 8192, 1536,
                new LlmCallGuard(mapper, mock(ExecutionRecorder.class)), new QwenTokenCounter(process));
        var messages = new ArrayList<LlmMessage>();
        messages.add(LlmMessage.text(LlmMessage.Role.SYSTEM, "system"));
        messages.add(LlmMessage.text(LlmMessage.Role.USER, "history and question"));
        try (var scope = ObservationContext.open(TokenBudgetGuardTest.context(events))) {
            client.chat(messages, List.of());
            var call = new LlmTurn.ToolCall("s1", "search_places", "{\"query\":\"야경\",\"limit\":5}");
            messages.add(LlmMessage.assistant(LlmTurn.builder().toolCalls(List.of(call)).build()));
            messages.add(LlmMessage.tool(call, "과거에는 통행할 수 없었다. 공사 조건."));
            var failure = assertThrows(TokenBudgetException.class, () -> client.chat(messages, List.of(
                    new LlmTurn.ToolDefinition("search_places", "search", mapper.createObjectNode()))));
            assertEquals(TokenBudgetException.Reason.CONTEXT_LIMIT, failure.reason());
        }
        assertEquals(2, counts.get());
        assertEquals("EXACT_LOCAL_CROSSCHECKED", events.get(1).path("payload").path("count").path("quality").asText());
        assertFalse(events.get(2).path("payload").path("dispatched").asBoolean());
        http.verify();
    }

    @Test
    void workerFailureAndMismatchedWireIdentityCannotReachInference() throws Exception {
        for (boolean mismatch : List.of(false, true)) {
            var builder = RestClient.builder().baseUrl("http://mock.invalid");
            var http = MockRestServiceServer.bindTo(builder).build();
            metadata(http);
            var process = mock(ExactQwenProcess.class);
            when(process.count(any())).thenAnswer(invocation -> {
                if (!mismatch) throw new IllegalStateException("MOCK counter failure");
                var result = (com.fasterxml.jackson.databind.node.ObjectNode) counted(invocation.getArgument(0), 10);
                return result.put("wireSha256", "different input");
            });
            var client = new OllamaLlmClient(builder.build(), "qwen3:8b", 8192, 1536,
                    new LlmCallGuard(mapper, mock(ExecutionRecorder.class)), new QwenTokenCounter(process));
            try (var scope = ObservationContext.open(TokenBudgetGuardTest.context(new ArrayList<>()))) {
                assertEquals(TokenBudgetException.Reason.COUNT_UNAVAILABLE,
                        assertThrows(TokenBudgetException.class, () -> client.generate("system", "original")).reason());
            }
            http.verify();
        }
    }

    @Test
    void missingProcessConfigurationFailsClosed() {
        assertThrows(IllegalStateException.class, () -> new ExactQwenProcess("[]", 1).count(mapper.createObjectNode()));
        assertThrows(IllegalArgumentException.class, () -> new ExactQwenProcess("\"shell command\"", 1));
        assertThrows(IllegalStateException.class, () -> new ExactQwenProcess("[\"missing-counter-executable.invalid\"]", 1)
                .count(mapper.createObjectNode()));
    }

    @Test
    void timeoutNonzeroExitAndMalformedOutputAreCountingFailures() throws Exception {
        String java = Path.of(System.getProperty("java.home"), "bin", "java.exe").toString();
        String classpath = Path.of(CounterProcessFixture.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toString();
        for (var scenario : CounterProcessFixture.Scenario.values()) {
            String command = mapper.writeValueAsString(List.of(java, "-cp", classpath, CounterProcessFixture.class.getName(), scenario.name()));
            assertThrows(IllegalStateException.class, () -> new ExactQwenProcess(command, 1).count(mapper.createObjectNode()));
        }
    }
}
