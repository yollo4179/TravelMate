package com.yollo.TravelMate.ai.llm.budget;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.function.Supplier;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;

/** How the input tokens of one request are bounded before it is dispatched. Exactly one method applies. */
public enum InputCountMethod {
    /**
     * OpenAI tokenizers are byte-level BPE, so each token covers at least one byte of the text it encodes, and the
     * JSON around that text is never tokenized itself. The UTF-8 length of the counted request is therefore an
     * upper bound; live requests carried 3.4 to 4.5 bytes per counted token. Usage is still checked against it.
     */
    UTF8_BYTE_BOUND {
        @Override
        boolean supports(InputCountPolicy policy, long countedBytes, long availableInput) {
            return policy == InputCountPolicy.LOCAL_BOUND_FIRST && countedBytes <= availableInput;
        }

        @Override
        TokenBudget.Count count(long countedBytes, long availableInput, Supplier<TokenBudget.Count> provider) {
            var evidence = JsonNodeFactory.instance.objectNode().put("utf8Bytes", countedBytes)
                    .put("availableInputTokens", availableInput);
            return new TokenBudget.Count(countedBytes, TokenBudget.Quality.CONSERVATIVE_BOUND, name(), null, evidence);
        }
    },
    /** The provider's own count, for a policy that requires it or a request too large for the byte bound. */
    PROVIDER_COUNT {
        @Override
        boolean supports(InputCountPolicy policy, long countedBytes, long availableInput) {
            return !UTF8_BYTE_BOUND.supports(policy, countedBytes, availableInput);
        }

        @Override
        TokenBudget.Count count(long countedBytes, long availableInput, Supplier<TokenBudget.Count> provider) {
            return provider.get();
        }
    };

    abstract boolean supports(InputCountPolicy policy, long countedBytes, long availableInput);

    abstract TokenBudget.Count count(long countedBytes, long availableInput, Supplier<TokenBudget.Count> provider);

    /** Counts {@code countedRequest}, the exact fields the provider would count, under {@code policy}. */
    public static TokenBudget.Count count(
            InputCountPolicy policy,
            JsonNode countedRequest,
            TokenBudget.Limits limits,
            Supplier<TokenBudget.Count> provider
    ) {
        long countedBytes = countedRequest.toString().getBytes(StandardCharsets.UTF_8).length;
        long availableInput = limits.contextTokens() - limits.outputReservation();
        var matching = Arrays.stream(values())
                .filter(method -> method.supports(policy, countedBytes, availableInput)).toList();
        if (matching.size() != 1) throw new IllegalStateException("Input count method must be unique: " + matching);
        return matching.get(0).count(countedBytes, availableInput, provider);
    }
}
