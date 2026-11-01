package com.yollo.TravelMate.ai.llm.budget;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.web.client.RestClient;

public final class QwenTokenCounter {
    private static final String SUPPORTED_TEMPLATE_SHA256 = "ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4";
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final long DYNAMIC_CONTROL_BYTES_PER_EXPANSION = 32;
    private QwenTokenCounter() {}

    public static TokenBudget.Count count(RestClient client, JsonNode request) {
        JsonNode metadata = client.post().uri("/api/show")
                .body(Map.of("model", request.path("model").asText(), "verbose", false))
                .retrieve().body(JsonNode.class);
        if (metadata == null) throw new IllegalStateException("Qwen metadata가 없습니다.");
        JsonNode model = metadata.path("model_info");
        String template = metadata.path("template").asText();
        String templateHash = LlmCallGuard.sha256(template);
        Long nativeContext = TokenBudget.reported(model, "qwen3.context_length");
        if (!"qwen3".equals(model.path("general.architecture").asText())
                || !"gpt2".equals(model.path("tokenizer.ggml.model").asText())
                || !"qwen2".equals(model.path("tokenizer.ggml.pre").asText())
                || !SUPPORTED_TEMPLATE_SHA256.equals(templateHash)
                || nativeContext == null || nativeContext < 1 || !request.path("messages").isArray()) {
            throw new IllegalStateException("Qwen 토크나이저·템플릿·한도 확인이 필요합니다.");
        }
        long variableBytes = utf8(metadata.path("system").asText(""));
        long expansions = 1 + request.path("messages").size() + request.path("tools").size();
        for (var message : request.path("messages")) {
            if (!message.path("content").isTextual()) throw new IllegalStateException("지원하지 않는 Qwen 입력입니다.");
            variableBytes = Math.addExact(variableBytes, utf8(message.path("content").textValue()));
            for (var call : message.path("tool_calls")) {
                variableBytes = Math.addExact(variableBytes, goJsonBytes(call));
                expansions++;
            }
        }
        for (var tool : request.path("tools")) variableBytes = Math.addExact(variableBytes, goJsonBytes(tool.path("function")));
        // 이 고정 Go 템플릿의 모든 분기 리터럴을 반복 상한으로 더한다. 실제 토큰 수라고 표시하지 않는다.
        String literals = template.replaceAll("(?s)\\{\\{.*?}}", "");
        long bound = Math.addExact(variableBytes, Math.multiplyExact(
                expansions, utf8(literals) + DYNAMIC_CONTROL_BYTES_PER_EXPANSION));
        var evidence = JSON.createObjectNode().put("templateSha256", templateHash)
                .put("tokenizer", "gpt2/qwen2 byte-level BPE").put("variableUtf8Bytes", variableBytes)
                .put("templateLiteralUtf8Bytes", utf8(literals)).put("expansionUpperBound", expansions)
                .put("nativeContextSource", "api/show model_info; metadata only, no generation");
        return new TokenBudget.Count(bound, TokenBudget.Quality.CONSERVATIVE_BOUND,
                "QWEN3_BYTE_BPE_TEMPLATE_UPPER_BOUND", nativeContext, evidence);
    }

    private static long goJsonBytes(JsonNode value) {
        String encoded = value.toString().replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
                .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029");
        return utf8(encoded);
    }

    private static long utf8(String value) { return value.getBytes(StandardCharsets.UTF_8).length; }
}
