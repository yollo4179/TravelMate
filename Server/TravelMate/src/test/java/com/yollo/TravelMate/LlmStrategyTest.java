package com.yollo.TravelMate;

import java.util.List;
import java.util.Map;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.derived.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.observation.ExecutionRecorder;
import com.yollo.TravelMate.domain.conversation.tool.ToolSchemas;
import com.yollo.TravelMate.domain.conversation.tool.SearchPlacesContract;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class LlmStrategyTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final List<LlmMessage> input = List.of(LlmMessage.text(LlmMessage.Role.USER, "검색해 줘"));
    private final List<LlmTurn.ToolDefinition> tools = List.of(new LlmTurn.ToolDefinition(
            "search_places", "검색", ToolSchemas.object(Map.of("query", ToolSchemas.text(2000)))));

    @Test
    void openAiPreservesOptionalSearchFieldsWithoutSilentlyRequiringThem() {
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        var optionalSearch = new LlmTurn.ToolDefinition("search_places", "search", SearchPlacesContract.parameters(), LlmTurn.SchemaMode.OPTIONAL_FIELDS);
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andExpect(jsonPath("$.tools[0].strict").value(false))
                .andExpect(jsonPath("$.tools[0].parameters.required.length()").value(1))
                .andExpect(jsonPath("$.tools[0].parameters.required[0]").value("query"))
                .andExpect(jsonPath("$.tools[0].parameters.properties.limit.default").value(10))
                .andExpect(jsonPath("$.tools[1].strict").value(true))
                .andRespond(withSuccess("{\"status\":\"completed\",\"output\":[]}", MediaType.APPLICATION_JSON));
        openAi(builder.build()).chat(input, List.of(optionalSearch, tools.get(0)));
        server.verify();
    }

    @Test
    void qwenReceivesTheSameOptionalSearchContractAsTheServer() {
        var builder = RestClient.builder().baseUrl("http://mock.invalid");
        var server = MockRestServiceServer.bindTo(builder).build();
        var optionalSearch = new LlmTurn.ToolDefinition("search_places", "search", SearchPlacesContract.parameters(), LlmTurn.SchemaMode.OPTIONAL_FIELDS);
        server.expect(requestTo("http://mock.invalid/api/chat"))
                .andExpect(jsonPath("$.tools[0].function.parameters.required.length()").value(1))
                .andExpect(jsonPath("$.tools[0].function.parameters.required[0]").value("query"))
                .andExpect(jsonPath("$.tools[0].function.parameters.properties.limit.default").value(10))
                .andRespond(withSuccess("{\"done\":true,\"message\":{\"role\":\"assistant\",\"content\":\"MOCK\"}}", MediaType.APPLICATION_JSON));
        new OllamaLlmClient(builder.build(), "qwen3:8b", 8192, 1536, wireOnlyGuard()).chat(input, List.of(optionalSearch));
        server.verify();
    }

    @ParameterizedTest
    @EnumSource(LlmProvider.class)
    void springSelectsOnePrimaryClientWithoutStartingAnyProviderRequest(LlmProvider provider) {
        new ApplicationContextRunner()
                .withBean(ObjectMapper.class, ObjectMapper::new)
                .withUserConfiguration(StrategyLlmClient.class, OllamaLlmClient.class, OpenAiLlmClient.class,
                        LlmCallGuard.class, ExecutionRecorder.class)
                .withPropertyValues("llm.provider=" + provider.name(), "ollama.exact-counter-command=[]")
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertInstanceOf(StrategyLlmClient.class, context.getBean(LlmClient.class));
                    assertEquals(2, context.getBeansOfType(LlmStrategy.class).size());
                });
    }

    @ParameterizedTest
    @EnumSource(LlmProvider.class)
    void exactlyOneSelectedStrategyHandlesBothLegacyGenerationAndChat(LlmProvider provider) {
        var selected = mock(LlmStrategy.class);
        var unused = mock(LlmStrategy.class);
        when(selected.supports(provider)).thenReturn(true);
        when(selected.generate("system", "user")).thenReturn("plan");
        var turn = LlmTurn.builder().content("reply").build();
        when(selected.chat(input, tools)).thenReturn(turn);
        var client = new StrategyLlmClient(List.of(selected, unused), provider);
        assertEquals("plan", client.generate("system", "user"));
        assertSame(turn, client.chat(input, tools));
        verify(unused, never()).generate(anyString(), anyString());
        verify(unused, never()).chat(anyList(), anyList());
        when(selected.chat(input, tools)).thenThrow(new IllegalStateException("failed"));
        assertThrows(IllegalStateException.class, () -> client.chat(input, tools));
        verify(unused, never()).chat(anyList(), anyList());
    }

    @Test
    void missingOrAmbiguousStrategyFailsInsteadOfFallingBackToAPaidProvider() {
        assertThrows(IllegalStateException.class, () -> new StrategyLlmClient(List.of(), LlmProvider.QWEN));
        var first = mock(LlmStrategy.class);
        var second = mock(LlmStrategy.class);
        when(first.supports(LlmProvider.QWEN)).thenReturn(true);
        when(second.supports(LlmProvider.QWEN)).thenReturn(true);
        assertThrows(IllegalStateException.class, () -> new StrategyLlmClient(List.of(first, second), LlmProvider.QWEN));
    }

    @Test
    void openAiReplaysFunctionCallIdsAndEncryptedReasoningBeforeToolResults() throws Exception {
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = openAi(builder.build());
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andExpect(header("Authorization", "Bearer test-key"))
                .andExpect(jsonPath("$.store").value(false))
                .andExpect(jsonPath("$.truncation").value("disabled"))
                .andExpect(jsonPath("$.tools[0].strict").value(true))
                .andExpect(jsonPath("$.tools[0].name").value("search_places"))
                .andRespond(withSuccess("""
                        {"status":"completed","output":[
                          {"type":"reasoning","id":"rs_mock","summary":[],"encrypted_content":"opaque-mock"},
                          {"type":"function_call","id":"fc_mock","call_id":"call_mock",
                           "name":"search_places","arguments":"{\\"query\\":\\"야경\\"}"}
                        ]}
                        """, MediaType.APPLICATION_JSON));
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andExpect(jsonPath("$.input[1].type").value("reasoning"))
                .andExpect(jsonPath("$.input[1].encrypted_content").value("opaque-mock"))
                .andExpect(jsonPath("$.input[2].call_id").value("call_mock"))
                .andExpect(jsonPath("$.input[3].type").value("function_call_output"))
                .andExpect(jsonPath("$.input[3].call_id").value("call_mock"))
                .andRespond(withSuccess("""
                        {"status":"completed","output":[{"type":"message","role":"assistant",
                         "content":[{"type":"output_text","text":"설명"}]}]}
                        """, MediaType.APPLICATION_JSON));
        var first = client.chat(input, tools);
        assertEquals("call_mock", first.toolCalls().get(0).id());
        assertEquals("야경", mapper.readTree(first.toolCalls().get(0).arguments()).get("query").textValue());
        var next = client.chat(List.of(input.get(0), LlmMessage.assistant(first),
                LlmMessage.tool(first.toolCalls().get(0), "{\"type\":\"PLACES\"}")), tools);
        assertEquals("설명", next.content());
        server.verify();
    }

    @Test
    void qwenReplaysObjectArgumentsAndToolNameAndKeepsExistingGenerationOptions() {
        var builder = RestClient.builder().baseUrl("http://mock.invalid");
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = new OllamaLlmClient(builder.build(), "qwen3:8b", 8192, 1536, wireOnlyGuard());
        server.expect(requestTo("http://mock.invalid/api/chat"))
                .andExpect(jsonPath("$.tools[0].function.name").value("search_places"))
                .andExpect(jsonPath("$.format").doesNotExist())
                .andExpect(jsonPath("$.think").value(false))
                .andRespond(withSuccess("""
                        {"done":true,"done_reason":"stop","message":{"role":"assistant","content":"",
                         "tool_calls":[{"function":{"name":"search_places","arguments":{"query":"야경"}}}]}}
                        """, MediaType.APPLICATION_JSON));
        server.expect(requestTo("http://mock.invalid/api/chat"))
                .andExpect(jsonPath("$.messages[1].tool_calls[0].function.arguments.query").value("야경"))
                .andExpect(jsonPath("$.messages[2].tool_name").value("search_places"))
                .andRespond(withSuccess("""
                        {"done":true,"done_reason":"stop","message":{"role":"assistant","content":"설명"}}
                        """, MediaType.APPLICATION_JSON));
        server.expect(requestTo("http://mock.invalid/api/chat"))
                .andExpect(jsonPath("$.format").value("json"))
                .andExpect(jsonPath("$.tools").doesNotExist())
                .andExpect(jsonPath("$.options.num_ctx").value(8192))
                .andExpect(jsonPath("$.options.num_predict").value(1536))
                .andRespond(withSuccess("""
                        {"done":true,"message":{"role":"assistant","content":"{}"}}
                        """, MediaType.APPLICATION_JSON));
        var first = client.chat(input, tools);
        assertEquals("설명", client.chat(List.of(input.get(0), LlmMessage.assistant(first),
                LlmMessage.tool(first.toolCalls().get(0), "근거")), tools).content());
        assertEquals("{}", client.generate("system JSON", "user"));
        server.verify();
    }

    @Test
    void openAiGenerationUsesConfiguredModelAndJsonWithoutChangingThePlannerContract() {
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = openAi(builder.build());
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andExpect(jsonPath("$.model").value("gpt-mock"))
                .andExpect(jsonPath("$.text.format.type").value("json_object"))
                .andExpect(jsonPath("$.tools").doesNotExist())
                .andRespond(withSuccess("""
                        {"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"{}"}]}]}
                        """, MediaType.APPLICATION_JSON));
        assertEquals("{}", client.generate("system JSON", "user"));
        server.verify();
    }

    @Test
    void missingOpenAiConfigurationNeverMakesAnHttpRequest() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = new OpenAiLlmClient(builder.build(), "", "", 1536);
        assertThrows(IllegalStateException.class, () -> client.chat(input, tools));
        server.verify();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "{\"status\":\"incomplete\",\"output\":[]}",
            "{\"status\":\"completed\",\"output\":[{\"type\":\"message\",\"content\":[{\"type\":\"refusal\",\"refusal\":\"no\"}]}]}"
    })
    void openAiIncompleteOrRefusedOutputCannotExecuteTools(String response) {
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = openAi(builder.build());
        server.expect(requestTo("https://mock.invalid/v1/responses")).andRespond(withSuccess(response, MediaType.APPLICATION_JSON));
        assertThrows(IllegalStateException.class, () -> client.chat(input, tools));
        server.verify();
    }

    private OpenAiLlmClient openAi(RestClient client) {
        return new OpenAiLlmClient(client, "test-key", TokenBudget.Limits.builder()
                .provider(LlmProvider.OPENAI).model("gpt-mock").contextTokens(16000).outputReservation(1536)
                .modelOutputLimit(4000).limitsModel("gpt-mock").limitsSource("mock fixture").build(), wireOnlyGuard());
    }

    private LlmCallGuard wireOnlyGuard() {
        var guard = mock(LlmCallGuard.class);
        when(guard.call(any(), any(), any(), any(), any(), any())).thenAnswer(invocation -> {
            java.util.function.Supplier<com.fasterxml.jackson.databind.JsonNode> inference = invocation.getArgument(3);
            java.util.function.Function<com.fasterxml.jackson.databind.JsonNode, LlmTurn> decode = invocation.getArgument(5);
            return decode.apply(inference.get());
        });
        return guard;
    }
}
