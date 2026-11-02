package com.yollo.TravelMate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.*;
import com.yollo.TravelMate.ai.llm.observation.*;
import com.yollo.TravelMate.domain.conversation.tool.SearchPlacesContract;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class OpenAiStrictToolContractTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final LlmTurn.ToolDefinition definition = new LlmTurn.ToolDefinition(
            "search_places", "fixture", SearchPlacesContract.parameters(), LlmTurn.SchemaMode.OPTIONAL_FIELDS);

    private OpenAiToolContracts.PreparedTool strictTool() {
        return OpenAiToolContracts.prepare(List.of(definition), OpenAiToolContracts.Mode.STRICT_SEARCH_V1).get(0);
    }

    private ObjectNode arguments() {
        var arguments = mapper.createObjectNode().put("query", "창경궁");
        for (String field : List.of("limit", "region", "city", "category", "exclude_place_ids", "area")) arguments.putNull(field);
        return arguments;
    }

    @Test
    void strictProjectionAndCanonicalContractRemainDistinctAndExportable() throws Exception {
        var strict = strictTool();
        assertTrue(strict.strict());
        assertEquals(7, strict.parameters().path("required").size());
        assertEquals(1, SearchPlacesContract.parameters().path("required").size());
        assertEquals(10, SearchPlacesContract.parameters().path("properties").path("limit").path("default").asInt());
        assertFalse(strict.parameters().toString().contains("uniqueItems"));
        assertFalse(strict.parameters().toString().contains("minLength"));
        assertFalse(strict.parameters().toString().contains("\"default\""));
        assertFalse(strict.parameters().path("additionalProperties").asBoolean());
        Path directory = Path.of("build/openai-strict-preparation");
        Files.createDirectories(directory);
        Files.writeString(directory.resolve("provider-schema.json"), strict.parameters().toPrettyString());
        Files.writeString(directory.resolve("server-schema.json"), SearchPlacesContract.parameters().toPrettyString());
    }

    @ParameterizedTest
    @ValueSource(strings = {"query", "limit", "region", "city", "category", "exclude_place_ids", "area"})
    void everyStrictFieldIsRequiredAndMissingQueryIsNeverGuessed(String missing) {
        var arguments = arguments();
        arguments.remove(missing);
        assertThrows(IllegalArgumentException.class, () -> strictTool().adapt(new LlmTurn.ToolCall("mock", "search_places", arguments.toString())));
    }

    @ParameterizedTest
    @ValueSource(strings = {"extra", "blank", "duplicates", "range", "tooLong"})
    void serverOnlyConstraintsStillRejectWithoutRemovingBadValues(String invalid) {
        var arguments = arguments();
        var mutations = java.util.Map.<String, Runnable>of(
                "extra", () -> arguments.putObject("searchContext").put("region", "서울"),
                "blank", () -> arguments.put("query", " "),
                "duplicates", () -> arguments.putArray("exclude_place_ids").add(378).add(378),
                "range", () -> arguments.put("limit", 21),
                "tooLong", () -> arguments.put("query", "x".repeat(2001))
        );
        mutations.get(invalid).run();
        assertThrows(IllegalArgumentException.class, () -> strictTool().adapt(new LlmTurn.ToolCall("mock", "search_places", arguments.toString())));
    }

    @Test
    void nullDefaultIsExplicitAndNativeContinuationIsNeverRewritten() throws Exception {
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        var limits = TokenBudget.Limits.builder().provider(LlmProvider.OPENAI).model("gpt-mock")
                .contextTokens(8192).outputReservation(1536).modelOutputLimit(128000)
                .limitsModel("gpt-mock").limitsSource("MOCK").build();
        var client = new OpenAiLlmClient(builder.build(), "MOCK-NOT-A-KEY", limits,
                new LlmCallGuard(mapper, mock(ExecutionRecorder.class)), OpenAiToolContracts.Mode.STRICT_SEARCH_V1, mock(OpenAiBatchBudget.class));
        String original = arguments().toString();
        var response = mapper.createObjectNode().put("status", "completed");
        response.putArray("output").addObject().put("type", "function_call").put("call_id", "mock-call")
                .put("name", "search_places").put("arguments", original);
        server.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andExpect(jsonPath("$.tools[0].strict").value(true))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":1000}", MediaType.APPLICATION_JSON));
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andExpect(jsonPath("$.tools[0].strict").value(true))
                .andRespond(withSuccess(response.toString(), MediaType.APPLICATION_JSON));
        server.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andExpect(jsonPath("$.input[1].arguments").value(original))
                .andExpect(jsonPath("$.input[2].output").value("原文・조건・부정은 그대로"))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":2000}", MediaType.APPLICATION_JSON));
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andExpect(jsonPath("$.input[1].arguments").value(original))
                .andRespond(withSuccess("{\"status\":\"completed\",\"output\":[]}", MediaType.APPLICATION_JSON));
        var messages = List.of(LlmMessage.text(LlmMessage.Role.USER, "MOCK"));
        List<JsonNode> events = new ArrayList<>();
        final LlmTurn first;
        try (var scope = ObservationContext.open(TokenBudgetGuardTest.context(events))) {
            first = client.chat(messages, List.of(definition));
        }
        assertEquals(10, mapper.readTree(first.toolCalls().get(0).arguments()).path("limit").asInt());
        assertEquals(original, first.continuation().get(0).path("arguments").asText());
        JsonNode adaptation = events.stream().filter(event -> "TOOL_ARGUMENT_ADAPTATION".equals(event.path("event").asText()))
                .findFirst().orElseThrow().path("payload");
        assertEquals(original, adaptation.path("originalArguments").asText());
        assertEquals(first.toolCalls().get(0).arguments(), adaptation.path("serverArguments").asText());
        Path directory = Path.of("build/openai-strict-preparation");
        Files.createDirectories(directory);
        Files.writeString(directory.resolve("mock-argument-adaptation.json"), adaptation.toPrettyString());
        client.chat(List.of(messages.get(0), LlmMessage.assistant(first), LlmMessage.tool(first.toolCalls().get(0), "原文・조건・부정은 그대로")), List.of(definition));
        server.verify();
    }
}
