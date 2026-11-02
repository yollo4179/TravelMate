package com.yollo.TravelMate.ai.llm.budget;

public final class QwenCounterException extends IllegalStateException {
    public enum Reason {
        NOT_CONFIGURED, CLOSED, QUEUE_TIMEOUT, INTERRUPTED, STARTUP_TIMEOUT,
        CALCULATION_TIMEOUT, WORKER_EXITED, PROTOCOL_FAILURE, WORKER_REJECTED, SESSION_INVALIDATED
    }

    private final Reason reason;

    public QwenCounterException(Reason reason) {
        super(reason.name());
        this.reason = reason;
    }

    public QwenCounterException(Reason reason, String workerError) {
        super(reason.name() + ":" + workerError);
        this.reason = reason;
    }

    public Reason reason() { return reason; }
}
