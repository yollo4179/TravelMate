package com.yollo.TravelMate.ai.llm.budget;

import java.util.Map;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.web.client.RestClient;

public final class QwenTokenCounter implements AutoCloseable {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String MODEL_DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41";
    private static final String TEMPLATE_SHA256 = "ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4";
    private final ExactQwenProcess process;

    public QwenTokenCounter(ExactQwenProcess process) { this.process = process; }

    public TokenBudget.Count count(RestClient client, JsonNode request) {
        try {
            return countVerified(client, request);
        } catch (RuntimeException exception) {
            if (!(exception instanceof QwenCounterException)) process.invalidate();
            throw exception;
        }
    }

    public boolean isConfigured() { return process.isConfigured(); }

    public JsonNode initialize(RestClient client, TokenBudget.Limits limits) {
        var wire = JSON.createObjectNode().put("model", limits.model()).put("think", false).put("stream", false);
        wire.putArray("messages");
        wire.putObject("options").put("temperature", 0.3).put("num_ctx", limits.contextTokens()).put("num_predict", limits.outputReservation());
        try {
            return process.initialize(metadataEnvelope(client, wire));
        } catch (RuntimeException exception) {
            if (!(exception instanceof QwenCounterException)) process.invalidate();
            throw exception;
        }
    }

    @Override
    public void close() { process.close(); }

    private JsonNode metadataEnvelope(RestClient client, JsonNode request) {
        JsonNode show = client.post().uri("/api/show")
                .body(Map.of("model", request.path("model").asText(), "verbose", false)).retrieve().body(JsonNode.class);
        JsonNode version = client.get().uri("/api/version").retrieve().body(JsonNode.class);
        JsonNode tags = client.get().uri("/api/tags").retrieve().body(JsonNode.class);
        if (show == null || version == null || tags == null) throw new IllegalStateException("Qwen identity metadata unavailable");
        var envelope = JSON.createObjectNode().put("wire", request.toString());
        envelope.set("show", show);
        envelope.set("version", version);
        envelope.set("tags", tags);
        return envelope;
    }

    private TokenBudget.Count countVerified(RestClient client, JsonNode request) {
        JsonNode envelope = metadataEnvelope(client, request);
        JsonNode show = envelope.path("show");
        JsonNode counted = process.count(envelope);
        Long inputTokens = counted == null ? null : TokenBudget.reported(counted, "inputTokens");
        if (inputTokens == null || !"EXACT_LOCAL_CROSSCHECKED".equals(counted.path("quality").asText())
                || !LlmCallGuard.sha256(request.toString()).equals(counted.path("wireSha256").asText())
                || !TEMPLATE_SHA256.equals(counted.path("templateSha256").asText())
                || !TEMPLATE_SHA256.equals(LlmCallGuard.sha256(show.path("template").asText()))
                || !MODEL_DIGEST.equals(counted.path("modelDigest").asText())
                || counted.path("nativeContextTokens").asLong() != 40960
                || !"0.40.13".equals(counted.path("serverVersion").asText())) {
            throw new IllegalStateException("Exact Qwen counter result identity mismatch");
        }
        return new TokenBudget.Count(
                inputTokens,
                TokenBudget.Quality.EXACT_LOCAL_CROSSCHECKED,
                "QWEN3_PINNED_GO_TEMPLATE_NATIVE_AND_INDEPENDENT_BPE",
                40960L,
                counted.deepCopy()
        );
    }
}
