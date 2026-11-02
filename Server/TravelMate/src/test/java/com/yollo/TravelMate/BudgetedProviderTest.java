package com.yollo.TravelMate;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.*;
import com.yollo.TravelMate.ai.llm.observation.*;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class BudgetedProviderTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void openAiCountsFullNativeInputAndPreservesProviderUsageAndReasoning() throws Exception {
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        List<JsonNode> events = new ArrayList<>();
        var guard = new LlmCallGuard(mapper, mock(ExecutionRecorder.class));
        var limits = TokenBudget.Limits.builder().provider(LlmProvider.OPENAI).model("gpt-mock")
                .contextTokens(1000).outputReservation(100).modelOutputLimit(100)
                .limitsModel("gpt-mock").limitsSource("MOCK model limits").build();
        var client = new OpenAiLlmClient(builder.build(), "test-key", limits, guard);
        JsonNode continuation = mapper.readTree("""
                {"type":"reasoning","id":"rs-mock","encrypted_content":"opaque-reasoning"}
                """);
        var messages = List.of(
                LlmMessage.text(LlmMessage.Role.SYSTEM, "원문과 부정·조건을 보존하라"),
                LlmMessage.text(LlmMessage.Role.USER, "과거 대화와 질문"),
                LlmMessage.builder().role(LlmMessage.Role.ASSISTANT).continuation(List.of(continuation)).build(),
                LlmMessage.tool(new LlmTurn.ToolCall("call-1", "search_places", "{}"), "공사로 통행할 수 없었다. 조건: 계단")
        );
        server.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andExpect(jsonPath("$.input[2].encrypted_content").value("opaque-reasoning"))
                .andExpect(jsonPath("$.input[3].output").value("공사로 통행할 수 없었다. 조건: 계단"))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":900}", MediaType.APPLICATION_JSON));
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andExpect(jsonPath("$.input[2].encrypted_content").value("opaque-reasoning"))
                .andExpect(jsonPath("$.max_output_tokens").value(100))
                .andRespond(withSuccess("""
                        {"status":"completed","id":"response-mock","usage":{"input_tokens":900,"output_tokens":30,
                         "output_tokens_details":{"reasoning_tokens":20},"input_tokens_details":{"cached_tokens":10}},
                         "output":[{"type":"message","content":[{"type":"output_text","text":"설명"}]}]}
                        """, MediaType.APPLICATION_JSON));
        try (var scope = ObservationContext.open(TokenBudgetGuardTest.context(events))) {
            assertEquals("설명", client.chat(messages, List.of()).content());
        }
        JsonNode finished = events.get(events.size() - 1).get("payload");
        assertEquals(900, finished.path("count").path("inputTokens").intValue());
        assertEquals("CONFIRMED_API", finished.path("count").path("quality").asText());
        assertEquals(30, finished.path("receipt").path("usage").path("outputTokens").intValue());
        assertEquals(20, finished.path("receipt").path("usage").path("reasoningTokens").intValue());
        assertFalse(finished.toString().contains("opaque-reasoning"), "reasoning 본문 대신 해시와 전체 입력 계산을 기록한다");
        server.verify();
    }

    @Test
    void openAiContextOverflowNeverReachesResponsesEndpoint() {
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        List<JsonNode> events = new ArrayList<>();
        var client = new OpenAiLlmClient(builder.build(), "test-key", TokenBudget.Limits.builder()
                .provider(LlmProvider.OPENAI).model("gpt-mock").contextTokens(100).outputReservation(20)
                .modelOutputLimit(50).limitsModel("gpt-mock").limitsSource("MOCK limits").build(),
                new LlmCallGuard(mapper, mock(ExecutionRecorder.class)));
        server.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":81}", MediaType.APPLICATION_JSON));
        try (var scope = ObservationContext.open(TokenBudgetGuardTest.context(events))) {
            assertThrows(TokenBudgetException.class, () -> client.generate("system", "원문·부정·조건"));
        }
        assertFalse(events.get(0).path("payload").path("dispatched").booleanValue());
        server.verify();
    }

}
