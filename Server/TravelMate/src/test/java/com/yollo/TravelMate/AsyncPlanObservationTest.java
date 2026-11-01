package com.yollo.TravelMate;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.observation.*;
import com.yollo.TravelMate.domain.conversation.data.*;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.place.data.result.*;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.repository.*;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import com.yollo.TravelMate.domain.plan.validator.ContextPlanResultValidator;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AsyncPlanObservationTest {
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();

    @Test
    void realExecutorPreservesParentTurnAndToolForTheAdditionalBudgetedModelCall() throws Exception {
        var request = mapper.readValue(PlanContextContractTest.REQUEST, GeneratePlanRequest.class);
        var jobs = mock(PlanningJobRepository.class);
        var plans = mock(ContextPlanRepository.class);
        var search = mock(PlaceSemanticSearchService.class);
        var llm = mock(LlmClient.class);
        var guard = new LlmCallGuard(mapper, mock(ExecutionRecorder.class));
        var status = new AtomicReference<>(PlanningResponse.JobStatus.QUEUED);
        var jobId = new AtomicReference<UUID>();
        var releaseWorker = new CountDownLatch(1);
        var workerEntered = new CountDownLatch(1);
        var workerObserved = new CountDownLatch(1);
        List<JsonNode> events = new CopyOnWriteArrayList<>();
        var root = ObservationContext.Context.builder().requestId("request-one").turnId("turn-one")
                .conversationId("conversation-mock").mode(ObservationContext.Mode.MOCK).phase(ObservationContext.Phase.REQUEST)
                .sink(event -> {
                    events.add(event.deepCopy());
                    if ("JOB_STATUS".equals(event.path("event").asText())
                            && "SUCCEEDED".equals(event.path("payload").path("status").asText())) workerObserved.countDown();
                }).build();
        when(jobs.insert(any(), anyString(), any(), any(), anyString())).thenAnswer(invocation -> {
            jobId.set(invocation.getArgument(0)); return true;
        });
        doAnswer(invocation -> { status.set(invocation.getArgument(1)); return null; })
                .when(jobs).update(any(), any(), any(), any());
        when(jobs.get(any(), eq("owner"))).thenAnswer(invocation -> new PlanningResponse.Job(
                jobId.get(), status.get(), "/mock-job", status.get() == PlanningResponse.JobStatus.SUCCEEDED ? 77L : null, null));
        var place = mapper.readValue("""
                {"id":101,"name":"모의 카페","category":"카페","latitude":35.8395,"longitude":129.212}
                """, PlaceResult.class);
        when(plans.requiredPlaces(List.of(101L))).thenReturn(List.of(place));
        when(search.search(anyString(), isNull(), isNull(), isNull(), eq(9), eq(request.context().area())))
                .thenReturn(List.of(new PlaceSemanticSearchResult(place, 0.8f)));
        when(plans.save(anyString(), any(), any(), anyList(), anyString())).thenReturn(77L);
        var draft = new PlanningResponse.Draft(
                77L, request.context(), "서버 초안",
                List.of(new PlanningResponse.Pin(101L, "모의 카페", 35.8395, 129.212, 60, 1)),
                List.of("실제 경로·운영시간 미검증"));
        when(plans.get(77L, "owner")).thenReturn(draft);
        var generated = new GeneratedPlan("초안", "모의 계획", List.of(
                new GeneratedPlan.GeneratedPin(101L, 1, "방문", "모의 근거")));
        when(llm.generate(anyString(), anyString())).thenAnswer(invocation -> {
            JsonNode wire = mapper.valueToTree(List.of(invocation.getArgument(0), invocation.getArgument(1)));
            return guard.call(limits(), wire, this::mockCount, () -> {
                workerEntered.countDown();
                try {
                    if (!releaseWorker.await(5, TimeUnit.SECONDS)) throw new IllegalStateException("mock worker timed out");
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException(exception);
                }
                return mapper.valueToTree(generated);
            }, response -> new TokenBudget.Receipt(TokenBudget.Usage.missing(), null, "MOCK"),
                    response -> LlmTurn.builder().content(response.toString()).build()).content();
        });
        var nextCall = new AtomicReference<>("generate_plan");
        var nextArguments = new AtomicReference<>("{}");
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            List<LlmMessage> history = invocation.getArgument(0);
            boolean withResult = history.get(history.size() - 1).role() == LlmMessage.Role.TOOL;
            var turn = withResult ? LlmTurn.builder().content("{\"message\":\"모의 설명\",\"citations\":[]}").build()
                    : LlmTurn.builder().toolCalls(List.of(new LlmTurn.ToolCall(
                            "generate_plan".equals(nextCall.get()) ? "generate-call" : "lookup-call",
                            nextCall.get(), nextArguments.get()))).build();
            return guard.call(limits(), mapper.valueToTree(history), this::mockCount,
                    () -> mapper.valueToTree(turn),
                    response -> new TokenBudget.Receipt(TokenBudget.Usage.missing(), mapper.valueToTree(turn.toolCalls()), "MOCK"),
                    response -> turn);
        });
        var prompts = new ContextPlanPromptFactory(mapper);
        var planning = new ContextPlanningService(jobs, plans, search, mapper, llm,
                new ContextPlanResultValidator(mapper), prompts);
        var mappedResults = new PlanningToolResults(planning, mapper);
        var registry = new ConversationToolRegistry(List.of(
                new GeneratePlanTool(planning, mappedResults), new GetPlanningJobTool(planning, mappedResults),
                new SearchPlacesTool(search, new PlaceSearchCriteriaResolver(), prompts, mapper)));
        var conversation = new ConversationService(llm, registry, new ConversationToolExecutor(registry, mapper),
                new ConversationAnswerRenderer(mapper), mapper, 6, 8);
        try {
            try (var scope = ObservationContext.open(root)) {
                var initial = conversation.respond("owner", UUID.randomUUID(), new ConversationRequest("초안", request, List.of()));
                assertEquals(ConversationResponse.ResultType.PLANNING_JOB, initial.type());
                assertFalse(initial.message().contains("완성됐습니다"));
            }
            assertNull(ObservationContext.capture());
            assertTrue(workerEntered.await(5, TimeUnit.SECONDS));
            releaseWorker.countDown();
            assertTrue(workerObserved.await(5, TimeUnit.SECONDS));
            nextCall.set("get_planning_job");
            nextArguments.set("{\"job_id\":\"" + jobId.get() + "\"}");
            try (var scope = ObservationContext.open(root.toBuilder().requestId("request-two").turnId("turn-two").build())) {
                var completed = conversation.respond("owner", UUID.randomUUID(), new ConversationRequest("상태", request, List.of()));
                assertEquals(ConversationResponse.ResultType.DRAFT, completed.type());
                assertEquals(mapper.valueToTree(draft), completed.data());
            }
            var workerCalls = events.stream().filter(event -> event.path("event").asText().equals("MODEL_CALL")
                    && event.path("phase").asText().equals("PLAN_GENERATION")
                    && event.path("payload").path("stage").asText().equals("FINISHED")).toList();
            assertEquals(1, workerCalls.size());
            var worker = workerCalls.get(0);
            assertEquals("request-one", worker.path("requestId").asText());
            assertEquals("turn-one", worker.path("turnId").asText());
            assertEquals("generate-call", worker.path("parentToolCallId").asText());
            assertEquals(jobId.get().toString(), worker.path("jobId").asText());
            assertEquals(5, events.stream().filter(event -> event.path("event").asText().equals("MODEL_CALL")
                    && event.path("payload").path("stage").asText().equals("FINISHED")).count());
            assertTrue(events.stream().allMatch(event -> event.path("mode").asText().equals("MOCK")));
        } finally {
            releaseWorker.countDown();
            ReflectionTestUtils.invokeMethod(planning, "shutdown");
        }
    }

    private TokenBudget.Limits limits() {
        return TokenBudget.Limits.builder().provider(LlmProvider.QWEN).model("qwen-mock").contextTokens(10000)
                .outputReservation(100).modelOutputLimit(100).limitsModel("qwen-mock").limitsSource("MOCK limits").build();
    }

    private TokenBudget.Count mockCount() {
        return new TokenBudget.Count(100, TokenBudget.Quality.CONFIRMED_API, "MOCK_COUNTER", null, mapper.nullNode());
    }
}
