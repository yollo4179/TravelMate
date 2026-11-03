package com.yollo.TravelMate;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.base.LlmMessage;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.*;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ConversationControlTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final LlmClient llm = mock(LlmClient.class);

    private enum ReceiptCase {
        SEARCH("search_places", ResultType.PLACES, "[{\"placeId\":378,\"name\":\"창경궁\"}]"),
        EMPTY_SEARCH("search_places", ResultType.PLACES, "[]"),
        GENERATE("generate_plan", ResultType.PLANNING_JOB, "{\"jobId\":\"job-1\",\"status\":\"QUEUED\"}"),
        JOB_STATUS("get_planning_job", ResultType.PLANNING_JOB, "{\"jobId\":\"job-1\",\"status\":\"RUNNING\"}"),
        DRAFT("get_planning_job", ResultType.DRAFT, "{\"planId\":77,\"status\":\"DRAFT\"}"),
        FUTURE_EDIT_TEST_DOUBLE("modify_plan", ResultType.DRAFT, "{\"planId\":77,\"version\":2,\"status\":\"DRAFT\"}"),
        FUTURE_MEMORY_TEST_DOUBLE("recall_memory", ResultType.TEXT, "{\"preference\":\"역사\"}");

        private final String toolName;
        private final ResultType resultType;
        private final String receipt;

        ReceiptCase(String toolName, ResultType resultType, String receipt) {
            this.toolName = toolName;
            this.resultType = resultType;
            this.receipt = receipt;
        }
    }

    @ParameterizedTest
    @EnumSource(ReceiptCase.class)
    void anyRegisteredToolReturnsServerReceiptWithoutAnExplanationCall(ReceiptCase scenario) throws Exception {
        var receipt = mapper.readTree(scenario.receipt);
        var tool = tool(scenario.toolName, scenario.resultType, receipt);
        when(llm.chat(anyList(), anyList())).thenReturn(call(scenario.toolName, "", "{}"));

        var response = service(List.of(tool), 4).respond("owner", UUID.randomUUID(), request());

        assertEquals(Termination.COMPLETED, response.termination());
        assertEquals(scenario.resultType, response.type());
        assertEquals(receipt, response.data());
        assertEquals(MessageSource.SERVER_RECEIPT, response.messageSource());
        assertEquals(1, response.modelTurns());
        assertEquals(1, response.toolResults().size());
        assertTrue(response.citations().isEmpty());
        assertFalse(response.message().contains("확정됐습니다"));
        verify(llm).chat(anyList(), argThat(definitions -> definitions.size() == 1
                && definitions.get(0).name().equals(scenario.toolName)));
        verifyNoMoreInteractions(llm);
        verify(tool).execute(any());
    }

    @ParameterizedTest
    @ValueSource(strings = {"안녕하세요. 어떤 여행을 준비하시나요?", "어느 날짜와 지역의 일정을 수정할까요?"})
    void oneModelCanAnswerOrClarifyWithoutExecutingATool(String message) throws Exception {
        var tool = tool("search_places", ResultType.PLACES, mapper.createArrayNode());
        when(llm.chat(anyList(), anyList())).thenReturn(answer(message));

        var response = service(List.of(tool), 4).respond("owner", UUID.randomUUID(), request());

        assertEquals(ResultType.TEXT, response.type());
        assertEquals(message, response.message());
        assertEquals(MessageSource.LLM, response.messageSource());
        assertEquals(1, response.modelTurns());
        verify(tool, never()).execute(any());
        verify(llm).chat(anyList(), anyList());
        verifyNoMoreInteractions(llm);
    }

    @Test
    void explicitReturnDoesNotRequireAnotherTurnEvenWithOnlyOneModelTurnAvailable() throws Exception {
        var tool = tool("search_places", ResultType.PLACES, mapper.createArrayNode());
        when(llm.chat(anyList(), anyList())).thenReturn(call("search_places", "{\"afterTool\":\"RETURN_RESULT\"}", "{}"));
        var response = service(List.of(tool), 1).respond("owner", UUID.randomUUID(), request());
        assertEquals(Termination.COMPLETED, response.termination());
        assertEquals("검색 조건에 맞는 장소가 없습니다.", response.message());
        verify(llm).chat(anyList(), anyList());
    }

    @Test
    void resultDependentWorkContinuesThroughTheSameModelWithActualToolOutput() throws Exception {
        var found = mapper.readTree("[{\"placeId\":378,\"name\":\"창경궁\"}]");
        var stored = mapper.readTree("{\"planId\":77,\"status\":\"DRAFT\"}");
        var search = tool("search_places", ResultType.PLACES, found);
        var generation = tool("generate_plan", ResultType.DRAFT, stored);
        var turns = new AtomicInteger();
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            List<LlmMessage> messages = invocation.getArgument(0);
            List<LlmTurn.ToolDefinition> tools = invocation.getArgument(1);
            assertEquals(2, tools.size());
            if (turns.getAndIncrement() == 0) {
                assertTrue(messages.stream().anyMatch(message -> message.content().contains("과거 대화")));
                return call("search_places", "{\"afterTool\":\"REASSESS\"}", "{}");
            }
            var actual = mapper.readTree(messages.get(messages.size() - 1).content());
            assertEquals(LlmMessage.Role.TOOL, messages.get(messages.size() - 1).role());
            assertEquals(found, actual.path("data"));
            return call("generate_plan", "", "{\"placeId\":" + actual.path("data").get(0).path("placeId").asLong() + "}");
        });

        var response = service(List.of(search, generation), 4).respond("owner", UUID.randomUUID(), request());

        assertEquals(Termination.COMPLETED, response.termination());
        assertEquals(2, response.modelTurns());
        assertEquals(stored, response.data());
        verify(generation).execute(argThat(invocation -> invocation.arguments().path("placeId").asLong() == 378));
        verify(llm, times(2)).chat(anyList(), anyList());
        verifyNoMoreInteractions(llm);
    }

    @ParameterizedTest
    @ValueSource(strings = {"{}", "[]", "완료했습니다", "{\"afterTool\":\"UNKNOWN\"}",
            "{\"afterTool\":null}", "{\"afterTool\":1}", "{\"afterTool\":\"REASSESS\"} {}",
            "{\"afterTool\":\"RETURN_RESULT\",\"message\":\"일정이 완성됐습니다\"}",
            "{\"message\":\"실행 결과를 미리 확정합니다\",\"citations\":[]}"})
    void invalidControlOrPrematureClaimsCannotExecuteToolsOrBecomeAnAnswer(String content) throws Exception {
        var tool = tool("generate_plan", ResultType.DRAFT, mapper.readTree("{\"planId\":77}"));
        when(llm.chat(anyList(), anyList())).thenReturn(call("generate_plan", content, "{}"));

        var response = service(List.of(tool), 4).respond("owner", UUID.randomUUID(), request());

        assertEquals(Termination.INVALID_RESPONSE, response.termination());
        assertTrue(response.toolResults().isEmpty());
        assertFalse(response.message().contains("완성됐습니다"));
        verify(tool, never()).execute(any());
        verify(llm).chat(anyList(), anyList());
    }

    @Test
    void failedExecutionKeepsFailureReceiptAndDoesNotSpendAnExplanationCall() throws Exception {
        var tool = tool("generate_plan", ResultType.DRAFT, mapper.createObjectNode());
        when(tool.execute(any())).thenThrow(new IllegalStateException("not executed successfully"));
        when(llm.chat(anyList(), anyList())).thenReturn(call("generate_plan", "", "{}"));

        var response = service(List.of(tool), 4).respond("owner", UUID.randomUUID(), request());

        assertEquals(Termination.TOOL_FAILED, response.termination());
        assertEquals(ResultType.ERROR, response.type());
        assertEquals("TOOL_FAILED", response.data().path("code").asText());
        assertEquals(ToolStatus.FAILED, response.toolResults().get(0).status());
        assertEquals(MessageSource.SERVER_RECEIPT, response.messageSource());
        verify(llm).chat(anyList(), anyList());
    }

    private ConversationTool tool(String name, ResultType type, JsonNode receipt) {
        var tool = mock(ConversationTool.class, CALLS_REAL_METHODS);
        when(tool.definition()).thenReturn(new LlmTurn.ToolDefinition(name, "offline test double", ToolSchemas.object(Map.of())));
        when(tool.execute(any())).thenReturn(ConversationTool.Result.builder().type(type).publicData(receipt).modelData(receipt).build());
        return tool;
    }

    @Test
    void aLaterFailureCannotTurnAnAcceptedPlanningJobIntoOverallSuccess() throws Exception {
        var accepted = mapper.readTree("{\"jobId\":\"job-1\",\"status\":\"QUEUED\"}");
        var generation = tool("generate_plan", ResultType.PLANNING_JOB, accepted);
        var search = tool("search_places", ResultType.PLACES, mapper.createArrayNode());
        when(search.execute(any())).thenThrow(new IllegalStateException("search unavailable"));
        when(llm.chat(anyList(), anyList())).thenReturn(LlmTurn.builder().toolCalls(List.of(
                new LlmTurn.ToolCall("generate-1", "generate_plan", "{}"),
                new LlmTurn.ToolCall("search-1", "search_places", "{}")
        )).build());

        var response = service(List.of(generation, search), 4).respond("owner", UUID.randomUUID(), request());

        assertEquals(Termination.TOOL_FAILED, response.termination());
        assertEquals(ResultType.PLANNING_JOB, response.type());
        assertEquals(accepted, response.data());
        assertTrue(response.message().contains("아직 초안이 완성되지 않았습니다"));
        assertTrue(response.message().contains("일부 도구 실행에 실패"));
        assertEquals(List.of(ToolStatus.SUCCEEDED, ToolStatus.FAILED),
                response.toolResults().stream().map(ToolObservation::status).toList());
        verify(llm).chat(anyList(), anyList());
    }

    private ConversationService service(List<ConversationTool> tools, int turns) {
        var registry = new ConversationToolRegistry(tools);
        return new ConversationService(
                llm,
                registry,
                new ConversationToolExecutor(registry, mapper),
                new ConversationAnswerRenderer(mapper),
                mapper,
                turns,
                8,
                new ConversationEvidencePreparation(List.of())
        );
    }

    private ConversationRequest request() {
        return new ConversationRequest("여행 요청", null, List.of(
                new ConversationRequest.HistoryMessage(ConversationRequest.HistoryRole.USER, "과거 대화")));
    }

    private LlmTurn call(String name, String content, String arguments) {
        return LlmTurn.builder().content(content)
                .toolCalls(List.of(new LlmTurn.ToolCall(UUID.randomUUID().toString(), name, arguments))).build();
    }

    private LlmTurn answer(String message) {
        var response = mapper.createObjectNode().put("message", message);
        response.putArray("citations");
        return LlmTurn.builder().content(response.toString()).build();
    }
}
