package com.yollo.TravelMate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.*;
import com.yollo.TravelMate.ai.llm.observation.ExecutionRecorder;
import com.yollo.TravelMate.domain.conversation.controller.EvaluationConversationContractController;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationGenerationPipeline;
import com.yollo.TravelMate.domain.conversation.service.ConversationAnswerContract;
import com.yollo.TravelMate.domain.conversation.tool.*;
import jakarta.validation.Validation;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.context.annotation.Profile;
import org.springframework.http.MediaType;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class ConversationEvaluationContractTest {
    private final ObjectMapper mapper = new ObjectMapper().registerModule(new JavaTimeModule());
    @TempDir
    Path temporary;

    private ConversationToolRegistry tools() {
        return new ConversationToolRegistry(List.of(
                new SearchPlacesTool(null, null, null, mapper),
                new GeneratePlanTool(null, null),
                new GetPlanningJobTool(null, null)
        ));
    }

    @Test
    void metadataUsesActualDefinitionsAndDoesNotExposeProviderSecrets() throws Exception {
        var environment = new MockEnvironment()
                .withProperty("llm.provider", "OPENAI").withProperty("openai.model", "offline-fixture")
                .withProperty("openai.api-key", "must-never-be-exported")
                .withProperty("jwt.secret", "must-never-be-exported")
                .withProperty("openai.conversation-response-format", "JSON_SCHEMA_V1")
                .withProperty("travelmate.conversation.max-model-turns", "1")
                .withProperty("travelmate.conversation.max-tool-calls", "2");
        var client = mock(LlmClient.class);
        var registry = tools();
        var endpoint = new EvaluationConversationContractController(registry, ConversationGenerationPipeline.defaults(client), environment);
        var user = com.yollo.TravelMate.domain.user.entity.User.builder().uid("offline-fixture-user").userId("aDMINuser").build();
        var contract = mapper.valueToTree(endpoint.contract(user));
        assertEquals("evaluation", contract.path("environment").asText());
        assertEquals(3, contract.path("tools").size());
        for (var definition : registry.definitions()) {
            var actual = java.util.stream.StreamSupport.stream(contract.path("tools").spliterator(), false)
                    .filter(tool -> tool.path("name").asText().equals(definition.name())).findFirst().orElseThrow();
            assertEquals(definition.parameters(), actual.path("parameters"));
        }
        assertFalse(contract.toString().contains("must-never-be-exported"));
        assertEquals("evaluation", EvaluationConversationContractController.class.getAnnotation(Profile.class).value()[0]);
        verifyNoInteractions(client);
        var target = Path.of("build/conversation-evaluation/contract.json");
        Files.createDirectories(target.getParent());
        mapper.writerWithDefaultPrettyPrinter().writeValue(target.toFile(), contract);
    }

    @Test
    void nativeSuitePlanningInputsPassTheActualServerDtoValidation() throws Exception {
        var suite = mapper.readTree(Path.of("../../Evaluation/datasets/conversation-smoke-v1/cases.json").toFile());
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            for (var caseDocument : suite.path("cases")) {
                if (!caseDocument.has("api_request")) continue;
                var request = mapper.treeToValue(caseDocument.path("api_request"), ConversationRequest.class);
                assertTrue(factory.getValidator().validate(request).isEmpty(), caseDocument.path("case_id").asText());
            }
        }
    }

    @Test
    void countAndInferenceUseTheSameStrictAnswerSchemaWithoutAddingAModel() throws Exception {
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        var requests = new ArrayList<JsonNode>();
        server.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andExpect(request -> requests.add(mapper.readTree(((org.springframework.mock.http.client.MockClientHttpRequest) request).getBodyAsString())))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":100}", MediaType.APPLICATION_JSON));
        var answer = mapper.createObjectNode().put("message", "원문에 근거한 모의 설명").put("answerKind", "PLACE_GUIDANCE").put("emotion", "GUIDING").put("intent", "RECOMMENDATION");
        answer.putArray("citations");
        var response = mapper.createObjectNode().put("status", "completed");
        response.putObject("usage").put("input_tokens", 100).put("output_tokens", 30);
        response.putArray("output").addObject().put("type", "message").putArray("content")
                .addObject().put("type", "output_text").put("text", answer.toString());
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andExpect(request -> requests.add(mapper.readTree(((org.springframework.mock.http.client.MockClientHttpRequest) request).getBodyAsString())))
                .andRespond(withSuccess(response.toString(), MediaType.APPLICATION_JSON));
        var limits = TokenBudget.Limits.builder().provider(LlmProvider.OPENAI).model("fixture-model")
                .contextTokens(8192).outputReservation(1536).modelOutputLimit(128000)
                .limitsModel("fixture-model").limitsSource("offline-known-limits").build();
        var client = new OpenAiLlmClient(builder.build(), "fixture-key", limits,
                new LlmCallGuard(mapper, new ExecutionRecorder(temporary.toString())), OpenAiToolContracts.Mode.STRICT_TOOLS_V1,
                new OpenAiBatchBudget(""), ConversationResponseFormat.JSON_SCHEMA_V1);
        var turn = client.chat(List.of(LlmMessage.text(LlmMessage.Role.USER, "질문과 이미 준비된 원문")), tools().definitions());
        assertEquals(answer, mapper.readTree(turn.content()));
        assertEquals(2, requests.size());
        assertEquals(requests.get(0).path("text"), requests.get(1).path("text"));
        assertEquals("json_schema", requests.get(1).path("text").path("format").path("type").asText());
        assertTrue(requests.get(1).path("text").path("format").path("strict").asBoolean());
        assertEquals(mapper.readTree(ConversationAnswerContract.schema().toString()), requests.get(1).path("text").path("format").path("schema"));
        server.verify();
    }
}
