package com.yollo.TravelMate.ai.llm.observation;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.UUID;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class ExecutionRecorder {
    private final Path directory;

    public ExecutionRecorder(@Value("${travelmate.observation.directory:build/observations}") String directory) {
        this.directory = Path.of(directory);
    }

    public synchronized void write(JsonNode event) {
        try {
            Files.createDirectories(directory);
            Files.writeString(directory.resolve("execution.jsonl"), event.toString() + "\n",
                    StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (java.io.IOException exception) {
            throw new IllegalStateException("실행 관측을 기록하지 못했습니다.", exception);
        }
    }

    public ObservationContext.Scope ensureScope() {
        if (ObservationContext.capture() != null) return () -> {};
        String id = UUID.randomUUID().toString();
        return ObservationContext.open(ObservationContext.Context.builder().requestId(id).turnId(id)
                .conversationId(id).mode(ObservationContext.Mode.UNSCOPED).phase(ObservationContext.Phase.REQUEST)
                .sink(this::write).build());
    }
}
