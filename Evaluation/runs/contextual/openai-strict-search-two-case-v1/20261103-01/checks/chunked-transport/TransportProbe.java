import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.*;
import com.yollo.TravelMate.ai.llm.observation.*;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.service.ConversationService;
import com.yollo.TravelMate.domain.conversation.tool.SearchPlacesTool;

public class TransportProbe {
    public static void main(String[] arguments) throws Exception {
        Path directory = Path.of(arguments[0]);
        var mapper = new ObjectMapper();
        var scope = mapper.readTree(directory.getParent().resolve("execution-scope.json").toFile());
        String model = scope.path("model").asText();
        var limits = TokenBudget.Limits.builder()
                .provider(LlmProvider.OPENAI)
                .model(model)
                .contextTokens(8192)
                .outputReservation(1536)
                .modelOutputLimit(128000)
                .limitsModel(model)
                .limitsSource("https://developers.openai.com/api/docs/models/gpt-5.4-mini")
                .build();
        var client = new OpenAiLlmClient(
                LlmHttpClients.create("http://127.0.0.1:18082/v1"),
                "OFFLINE-NOT-A-KEY",
                limits,
                new LlmCallGuard(mapper, new ExecutionRecorder(directory.resolve("observations").toString())),
                OpenAiToolContracts.Mode.STRICT_SEARCH_V1,
                new OpenAiBatchBudget(directory.resolve("approved-inference-policy.json").toString())
        );
        var promptField = ConversationService.class.getDeclaredField("SYSTEM_PROMPT");
        promptField.setAccessible(true);
        String systemPrompt = (String) promptField.get(null);
        var definition = new SearchPlacesTool(null, null, null, mapper).definition();
        for (var caseRequest : scope.path("case_requests")) {
            var request = mapper.treeToValue(caseRequest.path("api_request"), ConversationRequest.class);
            var userInput = mapper.createObjectNode().put("message", request.message());
            userInput.set("planningRequest", mapper.valueToTree(request.planningRequest()));
            userInput.set("searchContext", mapper.valueToTree(request.searchContext()));
            var messages = List.of(
                    LlmMessage.text(LlmMessage.Role.SYSTEM, systemPrompt),
                    LlmMessage.text(LlmMessage.Role.USER, userInput.toString())
            );
            var context = ObservationContext.Context.builder()
                    .requestId(caseRequest.path("case_id").asText())
                    .caseId(caseRequest.path("case_id").asText())
                    .inputSha256(caseRequest.path("input_sha256").asText())
                    .mode(ObservationContext.Mode.MOCK)
                    .phase(ObservationContext.Phase.CONVERSATION)
                    .sink(event -> {
                        try {
                            Files.writeString(directory.resolve("events.jsonl"), event + "\n",
                                    java.nio.file.StandardOpenOption.CREATE,
                                    java.nio.file.StandardOpenOption.APPEND);
                        } catch (Exception exception) {
                            throw new IllegalStateException(exception);
                        }
                    })
                    .build();
            try (var ignored = ObservationContext.open(context)) {
                client.chat(messages, List.of(definition));
            }
        }
    }
}
