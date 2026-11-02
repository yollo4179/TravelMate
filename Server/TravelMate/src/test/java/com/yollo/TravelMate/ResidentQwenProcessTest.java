package com.yollo.TravelMate;

import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.locks.ReentrantLock;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.OllamaLlmClient;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestClient;
import static com.yollo.TravelMate.CounterProcessFixture.Scenario;
import static com.yollo.TravelMate.ai.llm.budget.QwenCounterException.Reason;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ResidentQwenProcessTest {
    private final ObjectMapper mapper = new ObjectMapper();

    private ExactQwenProcess process(Scenario scenario, long seconds, long queueMillis, int capacity) throws Exception {
        String java = Path.of(System.getProperty("java.home"), "bin", "java.exe").toString();
        String classpath = Path.of(CounterProcessFixture.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toString();
        String command = mapper.writeValueAsString(List.of(java, "-cp", classpath, CounterProcessFixture.class.getName(), scenario.name()));
        return new ExactQwenProcess(command, seconds, queueMillis, capacity);
    }

    private JsonNode input(String original) { return mapper.createObjectNode().put("wire", original); }

    private void awaitBusy(ExactQwenProcess process) throws Exception {
        var lock = (ReentrantLock) ReflectionTestUtils.getField(process, "serial");
        assertNotNull(lock);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (!lock.isLocked() && System.nanoTime() < deadline) Thread.sleep(2);
        assertTrue(lock.isLocked());
    }

    @Test
    void reusesOneProcessAndCorrelatesEveryCompleteInputUntilClose() throws Exception {
        var process = process(Scenario.RESIDENT, 3, 1000, 2);
        JsonNode initialized = process.initialize(input("startup"));
        long pid = initialized.path("workerPid").asLong();
        String session = initialized.path("workerSessionId").asText();
        String previousId = null;
        for (int index = 1; index <= 3; index++) {
            String original = "과거에는 통행할 수 없었다. 조건과 원문. " + index;
            JsonNode result = process.count(input(original));
            assertEquals(pid, result.path("workerPid").asLong());
            assertEquals(session, result.path("workerSessionId").asText());
            assertEquals(index, result.path("sequence").asInt());
            assertEquals(1, result.path("initializationCount").asInt());
            assertEquals(original, result.path("echo").path("payload").path("wire").asText());
            String requestId = result.path("echo").path("requestId").asText();
            assertEquals(requestId, result.path("counterRequestId").asText());
            assertNotEquals(previousId, requestId);
            previousId = requestId;
        }
        process.close();
        assertEquals(ExactQwenProcess.State.CLOSED, process.state());
        assertTrue(ProcessHandle.of(pid).isEmpty() || !ProcessHandle.of(pid).orElseThrow().isAlive());
        assertEquals(Reason.CLOSED, assertThrows(QwenCounterException.class, () -> process.count(input("blocked"))).reason());
    }

    @Test
    void queueTimeoutDoesNotKillAnActiveHealthyCalculation() throws Exception {
        for (int capacity : List.of(0, 1)) {
            var threads = Executors.newFixedThreadPool(2);
            try (var process = process(Scenario.SLOW_COUNT, 4, 50, capacity)) {
                process.initialize(input("startup"));
                Future<JsonNode> first = threads.submit(() -> process.count(input("active")));
                awaitBusy(process);
                var failure = assertThrows(QwenCounterException.class, () -> process.count(input("queue rejected")));
                assertEquals(Reason.QUEUE_TIMEOUT, failure.reason());
                assertEquals("active", first.get(5, TimeUnit.SECONDS).path("echo").path("payload").path("wire").asText());
                assertEquals(ExactQwenProcess.State.READY, process.state());
            } finally { threads.shutdownNow(); }
        }
    }

    @Test
    void startupAndCalculationTimeoutsAreDifferentAndStaleQueuedRequestsCannotRestart() throws Exception {
        try (var process = process(Scenario.TIMEOUT, 1, 3000, 1)) {
            assertEquals(Reason.STARTUP_TIMEOUT, assertThrows(QwenCounterException.class,
                    () -> process.initialize(input("startup"))).reason());
        }
        var threads = Executors.newFixedThreadPool(2);
        try (var process = process(Scenario.SLOW_COUNT, 1, 3000, 1)) {
            process.initialize(input("startup"));
            Future<JsonNode> active = threads.submit(() -> process.count(input("times out")));
            awaitBusy(process);
            Future<JsonNode> queued = threads.submit(() -> process.count(input("must not use replacement worker")));
            var failure = assertThrows(ExecutionException.class, () -> active.get(4, TimeUnit.SECONDS));
            assertEquals(Reason.CALCULATION_TIMEOUT, ((QwenCounterException) failure.getCause()).reason());
            var stale = assertThrows(ExecutionException.class, () -> queued.get(4, TimeUnit.SECONDS));
            assertEquals(Reason.SESSION_INVALIDATED, ((QwenCounterException) stale.getCause()).reason());
            assertEquals(ExactQwenProcess.State.FAILED, process.state());
        } finally { threads.shutdownNow(); }
    }

    @Test
    void crashWrongRequestAndIdentityRejectionBlockTheCallThenRequireFreshInitialization() throws Exception {
        for (Scenario scenario : List.of(Scenario.CRASH_COUNT, Scenario.WRONG_ID, Scenario.REJECT_IDENTITY)) {
            try (var process = process(scenario, 3, 1000, 1)) {
                JsonNode initial = process.initialize(input("startup"));
                assertThrows(QwenCounterException.class, () -> process.count(input("must fail once")));
                assertEquals(ExactQwenProcess.State.FAILED, process.state());
                JsonNode restarted = process.initialize(input("fresh validation"));
                assertNotEquals(initial.path("workerSessionId"), restarted.path("workerSessionId"));
                assertEquals(1, restarted.path("initializationCount").asInt());
                assertEquals(ExactQwenProcess.State.READY, process.state());
            }
        }
    }

    @Test
    void providerLifecycleInitializesOnceWithoutInferenceAndClosesResources() {
        var counter = mock(QwenTokenCounter.class);
        when(counter.isConfigured()).thenReturn(true);
        when(counter.initialize(any(), any())).thenReturn(mapper.createObjectNode().put("initializationMs", 123));
        var guard = mock(LlmCallGuard.class);
        var client = new OllamaLlmClient(mock(RestClient.class), "qwen3:8b", 8192, 1536, guard, counter);
        client.initializeCounter();
        verify(counter).initialize(any(), argThat(limits -> limits.contextTokens() == 8192 && limits.outputReservation() == 1536));
        verifyNoInteractions(guard);
        client.closeCounter();
        verify(counter).close();
    }
}
