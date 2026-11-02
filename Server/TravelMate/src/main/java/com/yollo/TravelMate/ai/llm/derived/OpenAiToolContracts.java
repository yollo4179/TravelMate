package com.yollo.TravelMate.ai.llm.derived;

import java.util.List;
import java.util.Set;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.conversation.tool.SearchPlacesContract;
import com.yollo.TravelMate.domain.conversation.tool.ToolSchemas;

public final class OpenAiToolContracts {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final List<ContractStrategy> STRATEGIES = List.of(new StrictSearchStrategy(), new CanonicalStrategy());
    private static final String SEARCH_TOOL = "search_places";

    private OpenAiToolContracts() {}

    public enum Mode { CANONICAL, STRICT_SEARCH_V1 }
    private enum AdaptationStatus { ADAPTED, REJECTED }

    public record PreparedTool(LlmTurn.ToolDefinition definition, JsonNode parameters, boolean strict, ContractStrategy strategy) {
        public LlmTurn.ToolCall adapt(LlmTurn.ToolCall call) {
            return strategy.adapt(call, parameters);
        }
    }

    public static List<PreparedTool> prepare(List<LlmTurn.ToolDefinition> tools, Mode mode) {
        return tools.stream().map(tool -> {
            var matches = STRATEGIES.stream().filter(strategy -> strategy.supports(tool, mode)).toList();
            if (matches.size() != 1) throw new IllegalStateException("Ambiguous OpenAI tool contract");
            var strategy = matches.get(0);
            return new PreparedTool(tool, strategy.parameters(tool), strategy.strict(tool), strategy);
        }).toList();
    }

    public interface ContractStrategy {
        boolean supports(LlmTurn.ToolDefinition tool, Mode mode);
        JsonNode parameters(LlmTurn.ToolDefinition tool);
        boolean strict(LlmTurn.ToolDefinition tool);
        LlmTurn.ToolCall adapt(LlmTurn.ToolCall call, JsonNode parameters);
    }

    private static boolean isStrictSearch(LlmTurn.ToolDefinition tool, Mode mode) {
        return mode == Mode.STRICT_SEARCH_V1 && SEARCH_TOOL.equals(tool.name());
    }

    private static final class CanonicalStrategy implements ContractStrategy {
        public boolean supports(LlmTurn.ToolDefinition tool, Mode mode) { return !isStrictSearch(tool, mode); }
        public JsonNode parameters(LlmTurn.ToolDefinition tool) { return tool.parameters(); }
        public boolean strict(LlmTurn.ToolDefinition tool) { return tool.schemaMode() == LlmTurn.SchemaMode.STRICT; }
        public LlmTurn.ToolCall adapt(LlmTurn.ToolCall call, JsonNode parameters) { return call; }
    }

    private static final class StrictSearchStrategy implements ContractStrategy {
        public boolean supports(LlmTurn.ToolDefinition tool, Mode mode) { return isStrictSearch(tool, mode); }
        public boolean strict(LlmTurn.ToolDefinition tool) { return true; }

        public JsonNode parameters(LlmTurn.ToolDefinition tool) {
            if (!SearchPlacesContract.parameters().equals(tool.parameters())) {
                throw new IllegalArgumentException("Unsupported search contract for strict projection");
            }
            ObjectNode schema = SearchPlacesContract.parameters().deepCopy();
            var properties = (ObjectNode) schema.path("properties");
            properties.set("limit", ToolSchemas.nullable(properties.get("limit")));
            schema.putArray("required");
            properties.fieldNames().forEachRemaining(name -> schema.withArray("required").add(name));
            return supportedSchema(schema);
        }

        public LlmTurn.ToolCall adapt(LlmTurn.ToolCall call, JsonNode parameters) {
            var event = JSON.createObjectNode().put("provider", "OPENAI").put("contract", Mode.STRICT_SEARCH_V1.name())
                    .put("callId", call.id()).put("tool", call.name()).put("originalArguments", call.arguments());
            try {
                JsonNode providerArguments = JSON.reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(call.arguments());
                if (providerArguments == null) throw new IllegalArgumentException("Missing strict tool arguments");
                ToolSchemas.validate(parameters, providerArguments);
                ObjectNode serverArguments = providerArguments.deepCopy();
                // Null is the provider's explicit request for the server's existing omitted-limit default.
                if (serverArguments.path("limit").isNull()) {
                    serverArguments.put("limit", SearchPlacesContract.parameters().path("properties").path("limit").path("default").intValue());
                }
                SearchPlacesContract.validate(serverArguments);
                String encoded = serverArguments.toString();
                event.put("status", AdaptationStatus.ADAPTED.name()).put("serverArguments", encoded);
                ObservationContext.record(ObservationContext.Event.TOOL_ARGUMENT_ADAPTATION, event);
                return new LlmTurn.ToolCall(call.id(), call.name(), encoded);
            } catch (Exception exception) {
                event.put("status", AdaptationStatus.REJECTED.name()).putNull("serverArguments")
                        .put("reason", exception.getClass().getSimpleName());
                ObservationContext.record(ObservationContext.Event.TOOL_ARGUMENT_ADAPTATION, event);
                throw new IllegalArgumentException("Invalid OpenAI strict search arguments", exception);
            }
        }

        private JsonNode supportedSchema(JsonNode source) {
            if (source.isArray()) {
                var result = JSON.createArrayNode();
                source.forEach(item -> result.add(supportedSchema(item)));
                return result;
            }
            if (!source.isObject()) return source.deepCopy();
            var result = JSON.createObjectNode();
            // Length/uniqueness/default semantics remain enforced by the unchanged server contract.
            Set<String> serverOnly = Set.of("default", "minLength", "maxLength", "uniqueItems");
            source.properties().stream().filter(field -> !serverOnly.contains(field.getKey()))
                    .forEach(field -> result.set(field.getKey(), supportedSchema(field.getValue())));
            return result;
        }
    }
}
