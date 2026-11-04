package com.yollo.TravelMate;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.*;
import com.yollo.TravelMate.ai.llm.observation.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.http.MediaType;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class OpenAiBatchBudgetTest {
    @TempDir Path directory;
    private final ObjectMapper mapper = new ObjectMapper();
    private final TokenBudget.Limits limits = TokenBudget.Limits.builder().provider(LlmProvider.OPENAI).model("gpt-mock")
            .contextTokens(100).outputReservation(20).modelOutputLimit(100)
            .limitsModel("gpt-mock").limitsSource("MOCK").build();

    private ObjectNode policy() {
        var policy = mapper.createObjectNode().put("approved", true).put("inputCountBillingConfirmed", true)
                .put("inputCountBillingSource", "MOCK-only fixed request cost; not verified official billing")
                .put("model", "gpt-mock").put("contextCap", 100).put("outputReservation", 20)
                .put("maxCalls", 4).put("maxCallsPerCase", 2).put("inputUsdPerMillion", 1)
                .put("outputUsdPerMillion", 5).put("inputCountRequestMaxUsd", 0)
                .put("maxSpendUsd", new BigDecimal("0.001")).put("ledgerFile", "ledger.jsonl");
        policy.putObject("caseInputHashes").put("C1", "H1").put("C2", "H2");
        return policy;
    }

    private OpenAiBatchBudget budget(ObjectNode policy) throws Exception {
        Files.writeString(directory.resolve("policy.json"), policy.toString());
        return new OpenAiBatchBudget(directory.resolve("policy.json").toString());
    }

    private ObjectNode unverifiedPolicy() {
        var unverified = policy().put("inputCountCostPolicy", "ALLOW_UNVERIFIED")
                .put("maxInputCountRequests", 4).put("inputCountBillingConfirmed", false)
                .put("maxSpendUsd", new BigDecimal("0.00072"));
        unverified.putNull("inputCountBillingSource");
        unverified.putNull("inputCountRequestMaxUsd");
        return unverified;
    }

    @Test
    void explicitUnverifiedAllowancePreservesNullCostAndOnlyBoundsInference() throws Exception {
        var allowance = budget(unverifiedPolicy());
        try (var scope = context("C1", "R1")) {
            assertNull(allowance.reserve(limits).maximumUsd());
        }
        var event = mapper.readTree(Files.readString(directory.resolve("ledger.jsonl")));
        assertFalse(event.path("inputCountBillingConfirmed").asBoolean());
        assertFalse(event.path("totalCostBoundConfirmed").asBoolean());
        assertTrue(event.path("inputCountRequestMaxUsd").isNull());
        assertTrue(event.path("maximumUsd").isNull());
        assertTrue(event.path("batchReservedUsd").isNull());
        assertEquals(new BigDecimal("0.00018"), event.path("inferenceMaximumUsd").decimalValue());
        assertEquals("ALLOW_UNVERIFIED", event.path("inputCountCostPolicy").asText());
    }

    @ParameterizedTest
    @ValueSource(strings = {"missingAllowance", "unapproved", "claimedConfirmation", "zeroPrice", "claimedSource"})
    void unknownCountingCostsRemainBlockedWithoutAnHonestExplicitAllowance(String defect) throws Exception {
        var configuration = unverifiedPolicy();
        java.util.Map.<String, Runnable>of(
                "missingAllowance", () -> configuration.remove("inputCountCostPolicy"),
                "unapproved", () -> configuration.put("approved", false),
                "claimedConfirmation", () -> configuration.put("inputCountBillingConfirmed", true),
                "zeroPrice", () -> configuration.put("inputCountRequestMaxUsd", 0),
                "claimedSource", () -> configuration.put("inputCountBillingSource", "not verified")
        ).get(defect).run();
        var allowance = budget(configuration);
        try (var scope = context("C1", "R1")) {
            assertThrows(IllegalStateException.class, () -> allowance.reserve(limits));
        }
        assertFalse(Files.exists(directory.resolve("ledger.jsonl")));
    }

    @ParameterizedTest
    @CsvSource({"4,4,4", "4,3,3", "3,4,3"})
    void unverifiedAllowanceStillEnforcesBothCallCaps(
            int inferenceCap,
            int countingCap,
            int permitted
    ) throws Exception {
        var allowance = budget(unverifiedPolicy().put("maxCalls", inferenceCap).put("maxInputCountRequests", countingCap));
        for (int index = 0; index < permitted; index++) {
            String caseId = index < 2 ? "C1" : "C2";
            try (var scope = context(caseId, caseId)) {
                allowance.reserve(limits);
            }
        }
        try (var scope = context("C2", "C2")) {
            assertThrows(IllegalStateException.class, () -> allowance.reserve(limits));
        }
        assertEquals(permitted, Files.readAllLines(directory.resolve("ledger.jsonl")).size());
    }

    @Test
    void unverifiedAllowanceCannotExceedTheInferenceSpendLimit() throws Exception {
        var allowance = budget(unverifiedPolicy().put("maxSpendUsd", new BigDecimal("0.000179")));
        try (var scope = context("C1", "R1")) {
            assertThrows(IllegalStateException.class, () -> allowance.reserve(limits));
        }
        assertFalse(Files.exists(directory.resolve("ledger.jsonl")));
    }

    private ObservationContext.Scope context(String caseId, String requestId) {
        return ObservationContext.open(ObservationContext.Context.builder().requestId(requestId).turnId(requestId)
                .caseId(caseId).inputSha256("C1".equals(caseId) ? "H1" : "H2")
                .mode(ObservationContext.Mode.MOCK).phase(ObservationContext.Phase.CONVERSATION).sink(event -> {}).build());
    }

    @ParameterizedTest
    @ValueSource(strings = {"approved", "inputCountBillingConfirmed"})
    void unconfirmedPolicyBlocksBeforeBothCountingAndInferenceHttp(String missingConfirmation) throws Exception {
        var budget = budget(policy().put(missingConfirmation, false));
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = new OpenAiLlmClient(builder.build(), "MOCK-NOT-A-KEY", limits,
                new LlmCallGuard(mapper, mock(ExecutionRecorder.class)), OpenAiToolContracts.Mode.STRICT_SEARCH_V1, budget);
        try (var scope = context("C1", "R1")) {
            assertThrows(TokenBudgetException.class, () -> client.chat(List.of(LlmMessage.text(LlmMessage.Role.USER, "MOCK")), List.of()));
        }
        assertFalse(Files.exists(directory.resolve("ledger.jsonl")));
        server.verify();
    }

    @Test
    void strictModeWithoutAnExplicitBudgetCannotCallTheCountingEndpoint() {
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = new OpenAiLlmClient(builder.build(), "MOCK-NOT-A-KEY", limits,
                new LlmCallGuard(mapper, mock(ExecutionRecorder.class)), OpenAiToolContracts.Mode.STRICT_SEARCH_V1);
        assertThrows(TokenBudgetException.class, () -> client.chat(List.of(LlmMessage.text(LlmMessage.Role.USER, "MOCK")), List.of()));
        server.verify();
    }

    @Test
    void reservesAllFourCallsAndCannotResetBudgetByRestarting() throws Exception {
        var budget = budget(policy());
        try (var scope = context("C1", "R1")) {
            assertEquals(new BigDecimal("0.00018"), budget.reserve(limits).maximumUsd());
            budget.reserve(limits);
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
        try (var scope = context("C2", "R2")) {
            budget.reserve(limits);
            budget.reserve(limits);
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
        assertEquals(4, Files.readAllLines(directory.resolve("ledger.jsonl")).size());
        var restarted = new OpenAiBatchBudget(directory.resolve("policy.json").toString());
        try (var scope = context("C1", "R1")) {
            assertThrows(IllegalStateException.class, () -> restarted.reserve(limits));
        }
    }

    @Test
    void spendLimitAndUnknownCountingCostBlockBeforeLedgerAndHttp() throws Exception {
        var budget = budget(policy().put("maxSpendUsd", new BigDecimal("0.000179")));
        try (var scope = context("C1", "R1")) {
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
        assertFalse(Files.exists(directory.resolve("ledger.jsonl")));
        var unknown = budget(policy().putNull("inputCountRequestMaxUsd"));
        try (var scope = context("C1", "R1")) {
            assertThrows(IllegalStateException.class, () -> unknown.reserve(limits));
        }
    }

    @Test
    void aCaseCannotBeRepeatedWithANewRequestId() throws Exception {
        var budget = budget(policy());
        try (var scope = context("C1", "R1")) { budget.reserve(limits); }
        try (var scope = context("C1", "RETRY")) {
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
        try (var scope = context("UNAPPROVED", "R3")) {
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
    }

    @Test
    void planGenerationCannotSpendTheSearchOnlyAllowance() throws Exception {
        var budget = budget(policy());
        try (var scope = ObservationContext.open(ObservationContext.Context.builder().requestId("R1")
                .caseId("C1").inputSha256("H1").phase(ObservationContext.Phase.PLAN_GENERATION).jobId("MOCK-JOB")
                .mode(ObservationContext.Mode.MOCK).sink(event -> {}).build())) {
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
        assertFalse(Files.exists(directory.resolve("ledger.jsonl")));
    }

    @Test
    void explicitPlanAllowanceAdmitsOnlyTheQueuingCaseUpToItsCap() throws Exception {
        var budget = budget(policy().put("maxPlanGenerationCalls", 1));
        try (var scope = planGeneration("C1", "H1", "R1")) {
            assertNotNull(budget.reserve(limits));
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
        try (var scope = planGeneration("C2", "WRONG-HASH", "R2")) {
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
        var ledger = Files.readAllLines(directory.resolve("ledger.jsonl"));
        assertEquals(1, ledger.size());
        assertEquals("PLAN_GENERATION", mapper.readTree(ledger.get(0)).path("phase").asText());
        assertEquals("MOCK-JOB", mapper.readTree(ledger.get(0)).path("jobId").asText());
    }

    @Test
    void eachBackgroundJobKindHasItsOwnExplicitAllowance() throws Exception {
        var budget = budget(policy().put("maxPlanGenerationCalls", 1).put("maxRecommendationGenerationCalls", 1));
        try (var scope = ObservationContext.open(ObservationContext.Context.builder().requestId("R1").caseId("C1")
                .inputSha256("H1").phase(ObservationContext.Phase.RECOMMENDATION_GENERATION).jobId("MOCK-RECOMMENDATION")
                .mode(ObservationContext.Mode.MOCK).sink(event -> {}).build())) {
            assertNotNull(budget.reserve(limits));
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
        // The plan allowance is separate, so a spent recommendation allowance does not block the draft.
        try (var scope = planGeneration("C1", "H1", "R1")) {
            assertNotNull(budget.reserve(limits));
        }
        var unapproved = budget(policy().put("ledgerFile", "other-ledger.jsonl"));
        try (var scope = ObservationContext.open(ObservationContext.Context.builder().requestId("R2").caseId("C2")
                .inputSha256("H2").phase(ObservationContext.Phase.RECOMMENDATION_GENERATION).jobId("MOCK-RECOMMENDATION")
                .mode(ObservationContext.Mode.MOCK).sink(event -> {}).build())) {
            assertThrows(IllegalStateException.class, () -> unapproved.reserve(limits));
        }
    }

    private ObservationContext.Scope planGeneration(String caseId, String inputSha256, String requestId) {
        return ObservationContext.open(ObservationContext.Context.builder().requestId(requestId)
                .caseId(caseId).inputSha256(inputSha256).phase(ObservationContext.Phase.PLAN_GENERATION).jobId("MOCK-JOB")
                .mode(ObservationContext.Mode.MOCK).sink(event -> {}).build());
    }

    @Test
    void usageIsRecordedWithoutRefundingReservationsAndMissingUsageHaltsTheBatch() throws Exception {
        var budget = budget(policy());
        try (var scope = context("C1", "R1")) {
            var reservation = budget.reserve(limits);
            var count = new TokenBudget.Count(80, TokenBudget.Quality.CONFIRMED_API, "MOCK", null, mapper.nullNode());
            budget.observe(reservation, new TokenBudget.Receipt(new TokenBudget.Usage(80L, 10L, 2L, 0L), mapper.createArrayNode(), "completed"), count);
            var second = budget.reserve(limits);
            assertThrows(IllegalStateException.class, () -> budget.observe(second,
                    new TokenBudget.Receipt(TokenBudget.Usage.missing(), null, "failed"), count));
        }
        try (var scope = context("C2", "R2")) {
            assertThrows(IllegalStateException.class, () -> budget.reserve(limits));
        }
        var rows = Files.readAllLines(directory.resolve("ledger.jsonl"));
        assertTrue(rows.get(1).contains("USAGE_OBSERVED"));
        assertTrue(rows.get(2).contains("0.00036"));
        assertTrue(rows.get(3).contains("HALTED"));
    }

    @Test
    void realStrategyReservesBeforeCountAndPreservesReceiptOnStrictDecodeFailure() throws Exception {
        var budget = budget(policy());
        var builder = RestClient.builder().baseUrl("https://mock.invalid/v1");
        var server = MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("https://mock.invalid/v1/responses/input_tokens"))
                .andExpect(request -> assertTrue(Files.exists(directory.resolve("ledger.jsonl"))))
                .andRespond(withSuccess("{\"object\":\"response.input_tokens\",\"input_tokens\":80}", MediaType.APPLICATION_JSON));
        server.expect(requestTo("https://mock.invalid/v1/responses"))
                .andRespond(withSuccess("""
                        {"status":"completed","model":"gpt-mock","service_tier":"default",
                        "usage":{"input_tokens":80,"output_tokens":10},
                        "output":[{"type":"function_call","call_id":"mock-call","name":"search_places","arguments":"{}"}]}
                        """, MediaType.APPLICATION_JSON));
        var client = new OpenAiLlmClient(builder.build(), "MOCK-NOT-A-KEY", limits,
                new LlmCallGuard(mapper, mock(ExecutionRecorder.class)), OpenAiToolContracts.Mode.STRICT_SEARCH_V1, budget);
        var definition = new LlmTurn.ToolDefinition("search_places", "MOCK",
                com.yollo.TravelMate.domain.conversation.tool.SearchPlacesContract.parameters(), LlmTurn.SchemaMode.OPTIONAL_FIELDS);
        var events = new java.util.ArrayList<com.fasterxml.jackson.databind.JsonNode>();
        try (var scope = ObservationContext.open(ObservationContext.Context.builder().requestId("R1").turnId("R1")
                .caseId("C1").inputSha256("H1").mode(ObservationContext.Mode.MOCK)
                .phase(ObservationContext.Phase.CONVERSATION).sink(events::add).build())) {
            assertThrows(IllegalArgumentException.class, () -> client.chat(List.of(LlmMessage.text(LlmMessage.Role.USER, "MOCK")), List.of(definition)));
        }
        var finished = events.stream().filter(event -> event.path("event").asText().equals("MODEL_CALL")
                && event.path("payload").path("stage").asText().equals("FINISHED")).findFirst().orElseThrow();
        assertEquals(80, finished.path("payload").path("receipt").path("usage").path("inputTokens").asInt());
        assertTrue(Files.readString(directory.resolve("ledger.jsonl")).contains("HALTED_CALL_FAILURE"));
        try (var scope = context("C2", "R2")) { assertThrows(IllegalStateException.class, () -> budget.reserve(limits)); }
        server.verify();
    }
}
