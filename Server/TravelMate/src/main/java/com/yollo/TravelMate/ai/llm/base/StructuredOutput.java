package com.yollo.TravelMate.ai.llm.base;

import java.util.Objects;
import com.fasterxml.jackson.databind.JsonNode;

/** A named Strict JSON schema the caller requires for the final text, independent of whether tools are offered. */
public record StructuredOutput(
        String name,
        JsonNode schema
) {
    public StructuredOutput {
        Objects.requireNonNull(name);
        Objects.requireNonNull(schema);
        if (name.isBlank()) throw new IllegalArgumentException("Structured output needs a schema name");
    }
}
