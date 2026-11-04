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
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.budget.TokenBudgetException;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.repository.ContextPlanRepository;
import com.yollo.TravelMate.domain.plan.repository.PlanningJobRepository;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import com.yollo.TravelMate.domain.plan.validator.ContextPlanResultValidator;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** A failed draft is recorded with what the model wrote and why it was rejected; users see only a safe reason. */
class PlanGenerationFailureObservationTest {
    private static final String OWNER = "owner";
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();
    private final PlanningJobRepository jobs = mock(PlanningJobRepository.class);
    private final ContextPlanRepository plans = mock(ContextPlanRepository.class);
    private final PlaceSemanticSearchService search = mock(PlaceSemanticSearchService.class);
    private final LlmClient llm = mock(LlmClient.class);
    private final List<JsonNode> events = new CopyOnWriteArrayList<>();
    private final AtomicReference<String> storedError = new AtomicReference<>();
    private final AtomicReference<PlanningResponse.JobStatus> finalStatus = new AtomicReference<>();
    private final CountDownLatch finished = new CountDownLatch(1);
    private ContextPlanningService planning;
    private GeneratePlanRequest request;

    @BeforeEach
    void setUp() throws Exception {
        request = mapper.readValue(PlanContextContractTest.REQUEST, GeneratePlanRequest.class);
        var jobId = new AtomicReference<UUID>();
        when(jobs.insert(any(), anyString(), any(), any(), anyString())).thenAnswer(invocation -> {
            jobId.set(invocation.getArgument(0));
            return true;
        });
        when(jobs.get(any(), eq(OWNER))).thenAnswer(invocation -> new PlanningResponse.Job(
                jobId.get(), PlanningResponse.JobStatus.QUEUED, "/mock-job", null, null));
        doAnswer(invocation -> {
            PlanningResponse.JobStatus status = invocation.getArgument(1);
            if (status == PlanningResponse.JobStatus.FAILED || status == PlanningResponse.JobStatus.SUCCEEDED) {
                storedError.set(invocation.getArgument(3));
                finalStatus.set(status);
                finished.countDown();
            }
            return null;
        }).when(jobs).update(any(), any(), any(), any());
        var place = mapper.readValue("""
                {"id":101,"name":"모의 카페","category":"카페","latitude":35.8395,"longitude":129.212}
                """, PlaceResult.class);
        when(plans.requiredPlaces(List.of(101L))).thenReturn(List.of(place));
        when(search.search(anyString(), isNull(), isNull(), isNull(), anyInt(), eq(request.context().area())))
                .thenReturn(List.of(new PlaceSemanticSearchResult(place, 0.8f)));
        planning = new ContextPlanningService(jobs, plans, search, mapper, llm,
                new ContextPlanResultValidator(mapper), new ContextPlanPromptFactory(mapper));
    }

    @AfterEach
    void tearDown() {
        ReflectionTestUtils.invokeMethod(planning, "shutdown");
    }

    @Test
    void aBudgetFailureIsStoredAsAUserFacingReasonAndRecordedWithItsInternalCause() throws Exception {
        when(llm.generate(anyString(), anyString())).thenThrow(new TokenBudgetException(TokenBudgetException.Reason.COUNT_UNAVAILABLE));
        var draft = runUntilFailed();
        assertFalse(storedError.get().contains("토큰"), "users never see the budget internals");
        assertFalse(storedError.get().contains("COUNT_UNAVAILABLE"));
        assertEquals("TokenBudgetException", draft.path("failureType").asText());
        assertTrue(draft.path("failureMessage").asText().contains("COUNT_UNAVAILABLE"), "operators keep the real cause");
        assertTrue(draft.path("output").isNull(), "the model never answered");
        assertEquals(101L, draft.path("candidateIds").path(0).asLong());
    }

    @Test
    void anyModelCallFailureIsHiddenFromUsersNotOnlyTheBudgetGuard() throws Exception {
        when(llm.generate(anyString(), anyString())).thenThrow(new IllegalStateException("OpenAI evaluation call cap reached"));
        var draft = runUntilFailed();
        assertFalse(storedError.get().contains("OpenAI"), "provider and budget wording never reaches the job's public reason");
        assertEquals("IllegalStateException", draft.path("failureType").asText());
        assertEquals("OpenAI evaluation call cap reached", draft.path("failureMessage").asText());
    }

    @Test
    void aRejectedDraftKeepsTheExactModelOutputBesideTheReason() throws Exception {
        when(llm.generate(anyString(), anyString())).thenReturn("not a plan");
        var draft = runUntilFailed();
        assertEquals("FAILED", draft.path("status").asText());
        assertEquals("not a plan", draft.path("output").asText());
        assertFalse(draft.path("failureType").asText().isBlank());
        assertEquals("DRAFT_REJECTED", draft.path("failureKind").asText());
        assertTrue(draft.path("prompt").asText().contains("\"candidates\""), "the exact model input is kept for review");
    }

    // Live var2, var3, fy2: one mis-copied quote ("..." or a dropped word) used to fail the whole plan.
    @Test
    void aCitationThatFailsVerificationIsDroppedAndRecordedWhileTheDraftIsSaved() throws Exception {
        when(llm.generate(anyString(), anyString())).thenReturn("""
                {"planTitle":"초안","planDescription":"설명","dialogue":[],
                 "pins":[{"placeId":101,"sequence":1,"activity":"둘러보기","reason":"요청 장소",
                          "citations":[{"evidenceId":"E101-0","sourceId":"source","quote":"모의 ... 카페"}]}]}""");
        var draft = runUntilFinished();
        assertEquals(PlanningResponse.JobStatus.SUCCEEDED, finalStatus.get());
        assertEquals("SUCCEEDED", draft.path("status").asText());
        assertNull(storedError.get(), "a saved draft carries no error");
        assertEquals(1, draft.path("droppedCitations").size());
        assertEquals("NOT_DELIVERED_FOR_PLACE", draft.path("droppedCitations").get(0).path("reason").asText());
        assertEquals("모의 ... 카페", draft.path("droppedCitations").get(0).path("quote").asText(), "operators keep what was removed");
        verify(plans).save(anyString(), any(), any(), anyList(), anyString());
    }

    @Test
    void aModelCallFailureDoesNotClaimACauseNobodyVerified() throws Exception {
        when(llm.generate(anyString(), anyString())).thenThrow(new TokenBudgetException(TokenBudgetException.Reason.COUNT_UNAVAILABLE));
        var draft = runUntilFailed();
        assertEquals("GENERATION_UNAVAILABLE", draft.path("failureKind").asText());
        assertFalse(storedError.get().contains("응답하지 않"), "a passing outage was never verified");
        assertFalse(storedError.get().contains("잠시 후"), "nor that waiting fixes it");
    }

    private JsonNode runUntilFailed() throws Exception {
        var draft = runUntilFinished();
        assertEquals(PlanningResponse.JobStatus.FAILED, finalStatus.get());
        return draft;
    }

    private JsonNode runUntilFinished() throws Exception {
        var root = ObservationContext.Context.builder().requestId("request-one").turnId("turn-one")
                .conversationId("conversation-mock").mode(ObservationContext.Mode.MOCK).phase(ObservationContext.Phase.REQUEST)
                .sink(event -> events.add(event.deepCopy())).build();
        try (var scope = ObservationContext.open(root)) {
            planning.generate(OWNER, UUID.randomUUID(), request);
        }
        assertTrue(finished.await(5, TimeUnit.SECONDS));
        var drafts = events.stream().filter(event -> event.path("event").asText().equals("PLAN_DRAFT")).toList();
        assertEquals(1, drafts.size());
        assertEquals("request-one", drafts.get(0).path("requestId").asText(), "the draft stays bound to the turn that queued it");
        assertEquals("PLAN_GENERATION", drafts.get(0).path("phase").asText());
        return drafts.get(0).path("payload");
    }
}
