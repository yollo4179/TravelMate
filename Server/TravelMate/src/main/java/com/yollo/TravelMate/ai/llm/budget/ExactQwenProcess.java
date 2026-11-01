package com.yollo.TravelMate.ai.llm.budget;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

public class ExactQwenProcess {
    private static final ObjectMapper JSON = new ObjectMapper();
    private final List<String> command;
    private final long timeoutSeconds;

    public ExactQwenProcess(String commandJson, long timeoutSeconds) {
        if (timeoutSeconds < 1) throw new IllegalArgumentException("Counter timeout must be positive");
        try {
            JsonNode configured = JSON.readTree(commandJson);
            if (!configured.isArray()) throw new IllegalArgumentException("Counter command must be a JSON array");
            List<String> arguments = new ArrayList<>();
            configured.forEach(argument -> {
                if (!argument.isTextual() || argument.textValue().isBlank()) throw new IllegalArgumentException("Invalid counter command");
                arguments.add(argument.textValue());
            });
            this.command = List.copyOf(arguments);
            this.timeoutSeconds = timeoutSeconds;
        } catch (java.io.IOException exception) {
            throw new IllegalArgumentException("Invalid counter command configuration", exception);
        }
    }

    public JsonNode count(JsonNode envelope) {
        if (command.isEmpty()) throw new IllegalStateException("Exact Qwen counter is not configured");
        Path directory = null;
        Process process = null;
        try {
            directory = Files.createTempDirectory("travelmate-qwen-count-");
            Path input = directory.resolve("input.json");
            Path output = directory.resolve("output.json");
            Path error = directory.resolve("error.txt");
            Files.writeString(input, envelope.toString(), StandardCharsets.UTF_8);
            process = new ProcessBuilder(command).redirectInput(input.toFile()).redirectOutput(output.toFile())
                    .redirectError(error.toFile()).start();
            if (!process.waitFor(timeoutSeconds, TimeUnit.SECONDS)) throw new IllegalStateException("Exact token counter timed out");
            if (process.exitValue() != 0 || Files.size(output) > 65536) throw new IllegalStateException("Exact token counter failed");
            JsonNode counted = JSON.readTree(Files.readString(output, StandardCharsets.UTF_8));
            if (counted == null || !counted.isObject()) throw new IllegalStateException("Invalid exact token counter result");
            return counted;
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Exact token counter interrupted", exception);
        } catch (java.io.IOException exception) {
            throw new IllegalStateException("Exact token counter unavailable", exception);
        } finally {
            if (process != null && process.isAlive()) {
                process.descendants().forEach(ProcessHandle::destroyForcibly);
                process.destroyForcibly();
            }
            if (directory != null) {
                try (var files = Files.list(directory)) {
                    for (Path file : files.toList()) Files.deleteIfExists(file);
                    Files.deleteIfExists(directory);
                } catch (java.io.IOException exception) {
                    throw new IllegalStateException("Token counter temporary input cleanup failed", exception);
                }
            }
        }
    }
}
