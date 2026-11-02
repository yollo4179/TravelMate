package com.yollo.TravelMate.ai.llm.budget;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.HashMap;
import java.util.Map;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class OpenAiBatchBudget {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final BigDecimal MILLION = new BigDecimal("1000000");
    private final Policy policy;
    private final Path ledger;
    private final Map<String, String> caseRequests = new HashMap<>();
    private final Map<String, Integer> caseCalls = new HashMap<>();
    private BigDecimal reservedUsd = BigDecimal.ZERO;
    private int reservations;
    private boolean ledgerCreated;
    private boolean halted;

    public record Policy(
            boolean approved,
            boolean inputCountBillingConfirmed,
            String inputCountBillingSource,
            String model,
            long contextCap,
            long outputReservation,
            int maxCalls,
            int maxCallsPerCase,
            BigDecimal inputUsdPerMillion,
            BigDecimal outputUsdPerMillion,
            BigDecimal inputCountRequestMaxUsd,
            BigDecimal maxSpendUsd,
            Map<String, String> caseInputHashes,
            String ledgerFile
    ) {}

    public record Reservation(int ordinal, BigDecimal maximumUsd, String caseId) {}

    public void requireConfigured() {
        if (policy == null) throw new IllegalStateException("Strict service evaluation requires an explicit approved batch policy");
    }

    public OpenAiBatchBudget(@Value("${openai.evaluation-budget-file:}") String policyFile) {
        if (policyFile.isBlank()) {
            policy = null;
            ledger = null;
            return;
        }
        try {
            Path source = Path.of(policyFile).toAbsolutePath().normalize();
            policy = JSON.readValue(Files.readString(source), Policy.class);
            if (policy.ledgerFile() == null) throw new IllegalArgumentException("Missing budget ledger");
            ledger = source.getParent().resolve(policy.ledgerFile()).normalize();
            if (!ledger.startsWith(source.getParent()) || ledger.equals(source)) {
                throw new IllegalArgumentException("Budget ledger must be a separate file inside the policy directory");
            }
        } catch (Exception exception) {
            throw new IllegalArgumentException("Invalid OpenAI evaluation budget file", exception);
        }
    }

    public synchronized Reservation reserve(TokenBudget.Limits limits) {
        if (policy == null) return null;
        if (halted || !policy.approved() || !policy.inputCountBillingConfirmed()
                || policy.inputCountBillingSource() == null || policy.inputCountBillingSource().isBlank()) {
            throw new IllegalStateException("OpenAI evaluation approval and input-count billing confirmation required");
        }
        if (!limits.model().equals(policy.model()) || limits.contextTokens() != policy.contextCap()
                || limits.outputReservation() != policy.outputReservation()) {
            throw new IllegalStateException("OpenAI evaluation model/token configuration mismatch");
        }
        var context = ObservationContext.capture();
        if (context == null || context.phase() != ObservationContext.Phase.CONVERSATION || context.jobId() != null
                || context.caseId() == null || context.requestId() == null
                || policy.caseInputHashes() == null || context.inputSha256() == null
                || !context.inputSha256().equals(policy.caseInputHashes().get(context.caseId()))) {
            throw new IllegalStateException("OpenAI evaluation case/input binding required");
        }
        String previousRequest = caseRequests.get(context.caseId());
        if (previousRequest != null && !previousRequest.equals(context.requestId())) {
            throw new IllegalStateException("OpenAI evaluation case cannot be retried");
        }
        if (reservations >= policy.maxCalls() || caseCalls.getOrDefault(context.caseId(), 0) >= policy.maxCallsPerCase()) {
            throw new IllegalStateException("OpenAI evaluation call cap reached");
        }
        requireNonNegative(policy.inputUsdPerMillion());
        requireNonNegative(policy.outputUsdPerMillion());
        requireNonNegative(policy.inputCountRequestMaxUsd());
        requireNonNegative(policy.maxSpendUsd());
        long inputMaximum = Math.subtractExact(policy.contextCap(), policy.outputReservation());
        if (inputMaximum < 0) throw new IllegalStateException("Invalid OpenAI evaluation context cap");
        BigDecimal maximum = BigDecimal.valueOf(inputMaximum).multiply(policy.inputUsdPerMillion())
                .add(BigDecimal.valueOf(policy.outputReservation()).multiply(policy.outputUsdPerMillion()))
                .divide(MILLION).add(policy.inputCountRequestMaxUsd());
        if (reservedUsd.add(maximum).compareTo(policy.maxSpendUsd()) > 0) {
            throw new IllegalStateException("OpenAI evaluation spend cap reached before HTTP dispatch");
        }
        var reservation = new Reservation(reservations + 1, maximum, context.caseId());
        // Persist before either counting or inference; failed/unknown requests keep their entire reservation.
        var event = JSON.createObjectNode().put("stage", "RESERVED").put("ordinal", reservation.ordinal())
                .put("caseId", context.caseId()).put("requestId", context.requestId()).put("model", limits.model())
                .put("mode", context.mode().name())
                .put("maximumUsd", maximum).put("batchReservedUsd", reservedUsd.add(maximum));
        persist(event.toString());
        reservedUsd = reservedUsd.add(maximum);
        reservations++;
        caseRequests.put(context.caseId(), context.requestId());
        caseCalls.merge(context.caseId(), 1, Integer::sum);
        return reservation;
    }

    public synchronized void observe(Reservation reservation, TokenBudget.Receipt receipt, TokenBudget.Count countedInput) {
        if (reservation == null) return;
        var usage = receipt.usage();
        if (usage == null || usage.inputTokens() == null || usage.outputTokens() == null || countedInput == null
                || usage.inputTokens() < 0 || usage.inputTokens() > countedInput.inputTokens()
                || usage.outputTokens() < 0 || usage.outputTokens() > policy.outputReservation()) {
            halted = true;
            persist(JSON.createObjectNode().put("stage", "HALTED_USAGE_UNAVAILABLE_OR_OUTSIDE_RESERVATION")
                    .put("ordinal", reservation.ordinal()).toString());
            throw new IllegalStateException("OpenAI evaluation usage unavailable or outside reservation");
        }
        BigDecimal usageUpperCost = BigDecimal.valueOf(usage.inputTokens()).multiply(policy.inputUsdPerMillion())
                .add(BigDecimal.valueOf(usage.outputTokens()).multiply(policy.outputUsdPerMillion())).divide(MILLION);
        var event = JSON.createObjectNode().put("stage", "USAGE_OBSERVED").put("ordinal", reservation.ordinal())
                .put("inferenceUsageCostWithoutCacheDiscountUsd", usageUpperCost).put("invoiceConfirmed", false);
        event.set("usage", JSON.valueToTree(usage));
        persist(event.toString());
    }

    public synchronized void verifyProvider(Reservation reservation, com.fasterxml.jackson.databind.JsonNode response) {
        if (reservation == null) return;
        var identity = JSON.createObjectNode().put("stage", "PROVIDER_IDENTITY").put("ordinal", reservation.ordinal())
                .put("model", response.path("model").asText()).put("serviceTier", response.path("service_tier").asText());
        persist(identity.toString());
        if (!policy.model().equals(response.path("model").asText()) || !"default".equals(response.path("service_tier").asText())) {
            halted = true;
            throw new IllegalStateException("OpenAI evaluation returned model/service tier mismatch");
        }
    }

    public synchronized void halt(Reservation reservation) {
        if (reservation == null || halted) return;
        halted = true;
        persist(JSON.createObjectNode().put("stage", "HALTED_CALL_FAILURE").put("ordinal", reservation.ordinal()).toString());
    }

    private void persist(String event) {
        try {
            if (!ledgerCreated) {
                // CREATE_NEW prevents a second process or server restart from resetting an existing batch allowance.
                Files.writeString(ledger, event + "\n", StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
                ledgerCreated = true;
                return;
            }
            Files.writeString(ledger, event + "\n", StandardOpenOption.APPEND);
        } catch (Exception exception) {
            halted = true;
            throw new IllegalStateException("OpenAI evaluation ledger unavailable; HTTP dispatch blocked", exception);
        }
    }

    private static void requireNonNegative(BigDecimal amount) {
        if (amount == null || amount.signum() < 0) throw new IllegalStateException("Verified non-negative pricing required");
    }
}
