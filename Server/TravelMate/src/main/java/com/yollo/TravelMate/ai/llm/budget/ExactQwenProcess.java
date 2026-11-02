package com.yollo.TravelMate.ai.llm.budget;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import static com.yollo.TravelMate.ai.llm.budget.QwenCounterException.Reason;

public class ExactQwenProcess implements AutoCloseable {
    public enum State { NEW, READY, FAILED, CLOSED }
    private enum Operation { INIT, COUNT }
    private enum Status { READY, COUNTED, ERROR }
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final int MAX_RESPONSE_BYTES = 65536;
    private final List<String> command;
    private final long timeoutSeconds;
    private final long queueTimeoutMillis;
    private final Semaphore slots;
    private final ReentrantLock serial = new ReentrantLock(true);
    private final AtomicLong epoch = new AtomicLong();
    private volatile State state = State.NEW;
    private volatile boolean closed;
    private Process process;
    private ExecutorService transport;
    private InputStream output;
    private OutputStream input;
    private JsonNode initialization;
    private String sessionId;

    public ExactQwenProcess(String commandJson, long timeoutSeconds) {
        this(commandJson, timeoutSeconds, 5000, 8);
    }

    public ExactQwenProcess(
            String commandJson,
            long timeoutSeconds,
            long queueTimeoutMillis,
            int queueCapacity
    ) {
        if (timeoutSeconds < 1 || queueTimeoutMillis < 1 || queueCapacity < 0 || queueCapacity > 1024) {
            throw new IllegalArgumentException("Invalid counter lifecycle limits");
        }
        try {
            JsonNode configured = JSON.readTree(commandJson);
            if (configured == null || !configured.isArray()) throw new IllegalArgumentException("Counter command must be a JSON array");
            List<String> arguments = new ArrayList<>();
            configured.forEach(argument -> {
                if (!argument.isTextual() || argument.textValue().isBlank()) throw new IllegalArgumentException("Invalid counter command");
                arguments.add(argument.textValue());
            });
            if (!arguments.isEmpty()) arguments.add("--serve");
            this.command = List.copyOf(arguments);
            this.timeoutSeconds = timeoutSeconds;
            this.queueTimeoutMillis = queueTimeoutMillis;
            this.slots = new Semaphore(queueCapacity + 1, true);
        } catch (java.io.IOException exception) {
            throw new IllegalArgumentException("Invalid counter command configuration", exception);
        }
    }

    public boolean isConfigured() { return !command.isEmpty(); }
    public State state() { return state; }

    public JsonNode initialize(JsonNode envelope) {
        return execute(envelope, false);
    }

    public JsonNode count(JsonNode envelope) {
        return execute(envelope, true);
    }

    private JsonNode execute(JsonNode envelope, boolean calculate) {
        if (!isConfigured()) throw new QwenCounterException(Reason.NOT_CONFIGURED);
        if (closed) throw new QwenCounterException(Reason.CLOSED);
        long expectedEpoch = epoch.get();
        long queued = System.nanoTime();
        long deadline = queued + TimeUnit.MILLISECONDS.toNanos(queueTimeoutMillis);
        boolean acquiredSlot = false;
        boolean acquiredLock = false;
        try {
            acquiredSlot = slots.tryAcquire(queueTimeoutMillis, TimeUnit.MILLISECONDS);
            if (!acquiredSlot) throw new QwenCounterException(Reason.QUEUE_TIMEOUT);
            acquiredLock = serial.tryLock(Math.max(0, deadline - System.nanoTime()), TimeUnit.NANOSECONDS);
            if (!acquiredLock) throw new QwenCounterException(Reason.QUEUE_TIMEOUT);
            if (closed) throw new QwenCounterException(Reason.CLOSED);
            if (epoch.get() != expectedEpoch) throw new QwenCounterException(Reason.SESSION_INVALIDATED);
            double queueWaitMs = elapsed(queued);
            try {
                if (state != State.READY) start(envelope);
                synchronized (this) {
                    if (process == null || !process.isAlive()) throw new QwenCounterException(Reason.WORKER_EXITED);
                }
                if (!calculate) return initialization.deepCopy();
                long calculationStarted = System.nanoTime();
                JsonNode response = exchange(Operation.COUNT, envelope, Reason.CALCULATION_TIMEOUT);
                if (closed) throw new QwenCounterException(Reason.CLOSED);
                if (epoch.get() != expectedEpoch) throw new QwenCounterException(Reason.SESSION_INVALIDATED);
                ObjectNode counted = response.path("payload").deepCopy();
                counted.put("queueWaitMs", queueWaitMs);
                counted.put("counterRequestId", response.path("requestId").asText());
                counted.put("transportCalculationMs", elapsed(calculationStarted));
                return counted;
            } catch (RuntimeException exception) {
                invalidate();
                throw exception;
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new QwenCounterException(Reason.INTERRUPTED);
        } finally {
            if (acquiredLock) serial.unlock();
            if (acquiredSlot) slots.release();
        }
    }

    private void start(JsonNode envelope) {
        try {
            launch();
            JsonNode ready = exchange(Operation.INIT, envelope, Reason.STARTUP_TIMEOUT);
            sessionId = ready.path("sessionId").textValue();
            initialization = ready.path("payload").deepCopy();
            if (sessionId == null || sessionId.isBlank() || !sessionId.equals(initialization.path("workerSessionId").asText())) {
                throw new QwenCounterException(Reason.PROTOCOL_FAILURE);
            }
            synchronized (this) {
                if (closed) throw new QwenCounterException(Reason.CLOSED);
                state = State.READY;
            }
        } catch (java.io.IOException exception) {
            throw new QwenCounterException(Reason.WORKER_EXITED);
        }
    }

    private synchronized void launch() throws java.io.IOException {
        if (closed) throw new QwenCounterException(Reason.CLOSED);
        stopProcess();
        process = new ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.DISCARD).start();
        input = process.getOutputStream();
        output = process.getInputStream();
        transport = Executors.newSingleThreadExecutor(operation -> {
            Thread thread = new Thread(operation, "qwen-token-counter-transport");
            thread.setDaemon(true);
            return thread;
        });
    }

    private JsonNode exchange(Operation operation, JsonNode envelope, Reason timeoutReason) {
        String requestId = UUID.randomUUID().toString();
        ObjectNode frame = JSON.createObjectNode().put("requestId", requestId).put("operation", operation.name());
        frame.set("payload", envelope);
        final ExecutorService executor;
        final InputStream reader;
        final OutputStream writer;
        final String expectedSession;
        synchronized (this) {
            if (closed || transport == null || process == null || !process.isAlive()) {
                throw new QwenCounterException(closed ? Reason.CLOSED : Reason.WORKER_EXITED);
            }
            executor = transport;
            reader = output;
            writer = input;
            expectedSession = sessionId;
        }
        Future<JsonNode> pending = executor.submit(() -> {
            writer.write((frame.toString() + "\n").getBytes(StandardCharsets.UTF_8));
            writer.flush();
            ByteArrayOutputStream response = new ByteArrayOutputStream();
            for (int length = 0; length <= MAX_RESPONSE_BYTES; length++) {
                int next = reader.read();
                if (next < 0) throw new QwenCounterException(Reason.WORKER_EXITED);
                if (next == '\n') return JSON.readTree(response.toByteArray());
                response.write(next);
            }
            throw new QwenCounterException(Reason.PROTOCOL_FAILURE);
        });
        try {
            JsonNode response = pending.get(timeoutSeconds, TimeUnit.SECONDS);
            if (response == null || !response.isObject() || !requestId.equals(response.path("requestId").asText())) {
                throw new QwenCounterException(Reason.PROTOCOL_FAILURE);
            }
            Status status = Status.valueOf(response.path("status").asText());
            if (status == Status.ERROR) {
                if (Reason.CALCULATION_TIMEOUT.name().equals(response.path("errorCode").asText())) {
                    throw new QwenCounterException(Reason.CALCULATION_TIMEOUT);
                }
                throw new QwenCounterException(Reason.WORKER_REJECTED, response.path("errorCode").asText("UNKNOWN"));
            }
            if (!response.path("payload").isObject()
                    || (operation == Operation.INIT && status != Status.READY)
                    || (operation == Operation.COUNT && (status != Status.COUNTED
                        || !expectedSession.equals(response.path("sessionId").asText())))) {
                throw new QwenCounterException(Reason.PROTOCOL_FAILURE);
            }
            return response;
        } catch (TimeoutException exception) {
            pending.cancel(true);
            throw new QwenCounterException(timeoutReason);
        } catch (InterruptedException exception) {
            pending.cancel(true);
            Thread.currentThread().interrupt();
            throw new QwenCounterException(Reason.INTERRUPTED);
        } catch (ExecutionException exception) {
            if (exception.getCause() instanceof QwenCounterException counter) throw counter;
            throw new QwenCounterException(Reason.PROTOCOL_FAILURE);
        } catch (IllegalArgumentException exception) {
            throw new QwenCounterException(Reason.PROTOCOL_FAILURE);
        }
    }

    public synchronized void invalidate() {
        epoch.incrementAndGet();
        state = closed ? State.CLOSED : State.FAILED;
        stopProcess();
    }

    private synchronized void stopProcess() {
        if (process != null) {
            process.descendants().forEach(ProcessHandle::destroyForcibly);
            process.destroyForcibly();
            try { process.waitFor(5, TimeUnit.SECONDS); }
            catch (InterruptedException exception) { Thread.currentThread().interrupt(); }
        }
        if (transport != null) transport.shutdownNow();
        closePipe(input);
        closePipe(output);
        process = null;
        transport = null;
        input = null;
        output = null;
        sessionId = null;
        initialization = null;
    }

    private static void closePipe(java.io.Closeable pipe) {
        if (pipe == null) return;
        try { pipe.close(); }
        catch (java.io.IOException ignored) {
            // The process tree is already terminated; a closed OS pipe must not trigger a restart.
        }
    }

    @Override
    public synchronized void close() {
        closed = true;
        invalidate();
    }

    private static double elapsed(long started) { return (System.nanoTime() - started) / 1_000_000.0; }
}
