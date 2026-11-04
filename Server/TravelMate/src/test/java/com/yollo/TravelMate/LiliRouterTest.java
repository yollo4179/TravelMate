package com.yollo.TravelMate;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.base.LlmMessage;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.base.StructuredOutput;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.ConversationIntent;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.conversation.data.DisplayedResult;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliFixedLines;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchContext;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.MessageSource;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationGenerationPipeline;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationRoutingModule;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliPersona;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import com.yollo.TravelMate.domain.conversation.tool.GeneratePlanTool;
import com.yollo.TravelMate.domain.conversation.tool.GetPlanningJobTool;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class LiliRouterTest {
    private static final String OWNER = "owner";
    private static final String QUERY = "종로 조선 왕실 궁궐";
    private static final String FAILURE_REASON = "방문 체류시간이 여행 가능 시간을 초과합니다.";
    private String jobStatus = "QUEUED";
    private final ObjectMapper mapper = new ObjectMapper();
    private final LlmClient llm = mock(LlmClient.class);
    private final RecommendationJobService recommendations = mock(RecommendationJobService.class);
    private final List<ConversationTool.Invocation> planInvocations = new ArrayList<>();
    private final List<ConversationTool.Invocation> jobInvocations = new ArrayList<>();
    private final List<StructuredOutput> outputs = new ArrayList<>();
    private final List<List<LlmMessage>> prompts = new ArrayList<>();
    private LiliRouterV1 router;

    @BeforeEach
    void setUp() {
        var registry = new ConversationToolRegistry(List.of(
                recording(new GeneratePlanTool(null, null).definition(), planInvocations, ResultType.PLANNING_JOB),
                recording(new GetPlanningJobTool(null, null).definition(), jobInvocations, ResultType.PLANNING_JOB)));
        var renderer = new ConversationAnswerRenderer(mapper);
        var lili = new LiliTurns(ConversationGenerationPipeline.defaults(llm), mapper);
        var actions = new LiliActions(new ConversationToolExecutor(registry, mapper), lili, mapper);
        router = new LiliRouterV1(lili, List.of(
                new LiliReplyHandler(renderer),
                new LiliSearchHandler(recommendations, actions, renderer, mapper),
                new LiliPlanHandler(actions, renderer, mapper),
                new LiliJobHandler(actions, renderer, mapper)), renderer, mapper);
        var queued = mapper.createObjectNode().put("jobId", UUID.randomUUID().toString()).put("status", "QUEUED");
        when(recommendations.submit(anyString(), any(), any(), anyString())).thenReturn(ConversationTool.Result.builder()
                .type(ResultType.RECOMMENDATION_JOB).publicData(queued).modelData(queued).build());
    }

    @Test
    void chatEndsWithLilisCutWithoutSearchToolsOrEvidence() throws Exception {
        answer(decision("CHAT", "CONVERSATION", null, "HAPPY", "천만에! 오늘도 즐거웠어.", List.of()));
        var response = respond(new ConversationRequest("고마워. 오늘은 여기까지 할게.", null, List.of()));
        assertEquals(ResultType.TEXT, response.type());
        assertEquals(MessageSource.LLM, response.messageSource());
        assertEquals(CharacterEmotion.HAPPY, response.emotion());
        assertEquals(1, response.dialogue().size());
        assertTrue(response.toolResults().isEmpty());
        verifyNoInteractions(recommendations);
        assertEquals(LiliTurnContract.ROUTER_NAME, outputs.get(0).name());
        String system = prompts.get(0).get(0).content();
        assertTrue(system.contains(LiliPersona.text()), "the router speaks with the one shared persona");
        // Live runs offered lookups by plan name, exclusion by place name and booking help, none of which exist.
        assertTrue(system.contains("[할 수 있는 일과 그 방법]"));
        assertTrue(system.contains("작업 번호를 직접 적어야 한다"));
        assertTrue(system.contains("장소 이름으로 빼거나, 목록을 다시 보여 주는 일은 할 수 없다"));
        assertTrue(system.contains("예약에 필요한 정보 찾기나 정리"));
        assertFalse(prompts.get(0).get(1).content().contains("serverEvidence"), "LiLi decides before any place evidence");
    }

    @Test
    void clarificationOffersChoicesInsteadOfGuessing() throws Exception {
        answer(decision("CLARIFY", "RECOMMENDATION", null, "THINKING", "배고프구나! 어떤 게 땡겨?", List.of("든든한 식사", "카페랑 디저트")));
        var response = respond(new ConversationRequest("배고파", null, List.of()));
        assertEquals(List.of("든든한 식사", "카페랑 디저트"), response.choices());
        verifyNoInteractions(recommendations);
    }

    @Test
    void searchQueuesARecommendationJobWithLilisQuery() throws Exception {
        answer(decision("SEARCH_PLACES", "RECOMMENDATION", QUERY, "EXCITED", "오, 궁궐 좋지! 잠깐만 찾아볼게.", List.of()));
        var request = new ConversationRequest("종로에서 왕실 가족이 살던 궁을 둘러보고 싶어.", null, List.of());
        var response = respond(request);
        verify(recommendations).submit(eq(OWNER), any(), eq(request), eq(QUERY));
        assertEquals(ResultType.RECOMMENDATION_JOB, response.type());
        assertEquals("오, 궁궐 좋지! 잠깐만 찾아볼게.", response.message());
        assertEquals("search_places", response.toolResults().get(0).name());
        assertEquals(QUERY, mapper.readTree(response.toolResults().get(0).arguments()).path("query").asText());
    }

    @Test
    void planWithConditionsQueuesTheDraftWithLilisQueryAndKeepsHerLine() throws Exception {
        answer(decision("GENERATE_PLAN", "PLAN", QUERY, "EXCITED", "좋아, 일정 짜 볼게!", List.of()));
        var planning = new GeneratePlanRequest(null, GeneratePlanRequest.InputMethod.TEXT, List.of());
        var response = respond(new ConversationRequest("입력한 조건 그대로 일정 초안 생성을 요청해줘.", planning, List.of()));
        assertEquals(1, planInvocations.size());
        assertEquals(QUERY, planInvocations.get(0).request().planningRequest().searchQuery());
        assertEquals(ResultType.PLANNING_JOB, response.type());
        assertEquals("좋아, 일정 짜 볼게!", response.message());
        assertEquals(1, outputs.size(), "a queued job needs no second model call");
    }

    @Test
    void planWithoutConditionsAsksBackAndNeverQueuesAJob() throws Exception {
        answer(decision("GENERATE_PLAN", "PLAN", QUERY, "EXCITED", "좋아, 일정 짜 볼게!", List.of()),
                reply("PLAN", "THINKING", "언제 어디로 갈지 먼저 알려줄래?", List.of("이번 주말", "다음 달")));
        var response = respond(new ConversationRequest("서울 여행 일정을 만들어줘.", null, List.of()));
        assertTrue(planInvocations.isEmpty());
        assertEquals("언제 어디로 갈지 먼저 알려줄래?", response.message());
        assertEquals(LiliTurnContract.REPLY_NAME, outputs.get(1).name());
        String followUp = lastUserInput(1);
        assertTrue(followUp.contains(LiliServerCode.PLANNING_CONDITIONS_MISSING.situation()));
        assertFalse(followUp.contains(LiliServerCode.PLANNING_CONDITIONS_MISSING.name()), "LiLi never reads an internal code");
    }

    @Test
    void knownJobStatusIsToldWithAFixedLineAfterLilisCutWithoutASecondModelCall() throws Exception {
        String jobId = UUID.randomUUID().toString();
        answer(decision("GET_PLANNING_JOB", "PLAN", null, "THINKING", "확인해 볼게.", List.of()));
        var response = respond(new ConversationRequest("내 생성 작업 " + jobId + "의 현재 상태를 확인해줘.", null, List.of()));
        assertEquals(1, jobInvocations.size());
        assertEquals(jobId, jobInvocations.get(0).arguments().path("job_id").asText());
        assertEquals(List.of(new DialogueCut("확인해 볼게.", CharacterEmotion.THINKING), LiliFixedLines.line(JobStatus.QUEUED)),
                response.dialogue());
        assertEquals(1, outputs.size(), "a known status needs no follow-up call");
        assertTrue(lastUserInput(0).contains("\"jobIdProvided\":true"));
    }

    @Test
    void failedJobIsExplainedByLiliWithTheUserFacingReasonOnly() throws Exception {
        jobStatus = "FAILED";
        String jobId = UUID.randomUUID().toString();
        answer(decision("GET_PLANNING_JOB", "PLAN", null, "THINKING", "확인해 볼게.", List.of()),
                reply("PLAN", "SAD", "이번 일정은 시간이 모자라서 못 만들었어. 조건을 바꿔서 다시 해 볼까?", List.of("시간 늘리기")));
        var response = respond(new ConversationRequest("작업 " + jobId + " 어떻게 됐어?", null, List.of()));
        String followUp = lastUserInput(1);
        assertTrue(followUp.contains(LiliServerCode.PLAN_GENERATION_FAILED.situation()));
        assertTrue(followUp.contains(FAILURE_REASON));
        assertFalse(followUp.contains("FAILED"), "status codes stay on the server");
        assertTrue(response.choices().isEmpty(), "a failure is not a question, so no choices");
    }

    @Test
    void jobStatusWithoutAnIdAsksWhichJobAndRunsNoTool() throws Exception {
        answer(decision("GET_PLANNING_JOB", "PLAN", null, "THINKING", "확인해 볼게.", List.of()),
                reply("PLAN", "THINKING", "어떤 작업인지 알려줄래?", List.of()));
        var response = respond(new ConversationRequest("내 일정 생성 작업이 어디까지 됐어?", null, List.of()));
        assertTrue(jobInvocations.isEmpty());
        assertEquals("어떤 작업인지 알려줄래?", response.message());
        assertTrue(lastUserInput(1).contains(LiliServerCode.JOB_ID_NOT_FOUND.situation()));
        assertFalse(lastUserInput(1).contains(LiliServerCode.JOB_ID_NOT_FOUND.name()));
        assertTrue(lastUserInput(0).contains("\"jobIdProvided\":false"));
    }

    @Test
    void positionsAreMappedOntoTheDisplayedListAndMergedIntoTheAppsExclusions() throws Exception {
        answer(decision("SEARCH_PLACES", "RECOMMENDATION", QUERY, List.of(1), "GUIDING", "알겠어, 그건 빼고 다시 찾아볼게.", List.of()));
        var context = new PlaceSearchContext("서울", "종로", "관광지", List.of(99L), null);
        var displayed = new DisplayedResult(UUID.randomUUID(), List.of(11L, 22L, 33L));
        var request = new ConversationRequest("첫 번째는 빼고 다시 찾아줘", null, List.of(), context, ConversationIntent.AUTO, displayed);
        var response = respond(request);
        var submitted = org.mockito.ArgumentCaptor.forClass(ConversationRequest.class);
        verify(recommendations).submit(eq(OWNER), any(), submitted.capture(), eq(QUERY));
        assertEquals(List.of(99L, 11L), submitted.getValue().searchContext().excludePlaceIds());
        assertEquals("종로", submitted.getValue().searchContext().city(), "other filters stay as the app sent them");
        var arguments = mapper.readTree(response.toolResults().get(0).arguments());
        assertEquals(11L, arguments.path("exclude_place_ids").path(0).asLong());
        assertTrue(lastUserInput(0).contains("\"displayedResultCount\":3"));
    }

    @Test
    void anExclusionWithoutTheDisplayedListAsksBackAndNeverSearches() throws Exception {
        answer(decision("SEARCH_PLACES", "RECOMMENDATION", QUERY, List.of(1), "GUIDING", "그건 빼고 찾아볼게.", List.of()),
                reply("RECOMMENDATION", "THINKING", "어떤 장소를 뺄지 알려줄래?", List.of("이름으로 말하기", "목록 다시 보기")));
        var response = respond(new ConversationRequest("첫 번째는 빼고 다시 찾아줘", null, List.of()));
        verifyNoInteractions(recommendations);
        assertTrue(lastUserInput(1).contains(LiliServerCode.DISPLAYED_RESULT_MISSING.situation()));
        assertEquals(List.of("이름으로 말하기", "목록 다시 보기"), response.choices());
    }

    @Test
    void aPositionPastTheDisplayedListAsksBackInsteadOfGuessing() throws Exception {
        answer(decision("SEARCH_PLACES", "RECOMMENDATION", QUERY, List.of(5), "GUIDING", "그건 빼고 찾아볼게.", List.of()),
                reply("RECOMMENDATION", "THINKING", "목록에 다섯 번째는 없는 것 같아. 어떤 걸 뺄까?", List.of()));
        var displayed = new DisplayedResult(UUID.randomUUID(), List.of(11L, 22L));
        respond(new ConversationRequest("다섯 번째 빼줘", null, List.of(), null, ConversationIntent.AUTO, displayed));
        verifyNoInteractions(recommendations);
        assertTrue(lastUserInput(1).contains(LiliServerCode.EXCLUDE_POSITION_OUT_OF_RANGE.situation()));
    }

    @Test
    void aSearchDecisionWithoutAQueryFallsBackInsteadOfSearchingTheRawSentence() throws Exception {
        answer(decision("SEARCH_PLACES", "RECOMMENDATION", null, "EXCITED", "찾아볼게!", List.of()));
        var response = respond(new ConversationRequest("아무 데나 찾아줘", null, List.of()));
        assertEquals(Termination.INVALID_RESPONSE, response.termination());
        verifyNoInteractions(recommendations);
    }

    @Test
    void routerSchemaDecidesBeforeItSpeaks() {
        var order = new ArrayList<String>();
        LiliTurnContract.routerSchema().path("properties").fieldNames().forEachRemaining(order::add);
        assertEquals(List.of("branch", "intent", "search_query", "exclude_positions", "emotion", "message", "choices"), order);
        var recommendation = new ArrayList<String>();
        LiliTurnContract.recommendationSchema().path("properties").fieldNames().forEachRemaining(recommendation::add);
        assertTrue(recommendation.indexOf("citations") < recommendation.indexOf("dialogue"));
    }

    private String lastUserInput(int call) {
        var messages = prompts.get(call);
        return messages.get(messages.size() - 1).content();
    }

    private ConversationResponse respond(ConversationRequest request) {
        return router.execute(new ConversationRoutingModule.Turn(OWNER, UUID.randomUUID(), request));
    }

    private void answer(String... contents) {
        var queue = new ArrayList<>(List.of(contents));
        when(llm.chat(anyList(), anyList(), any(StructuredOutput.class))).thenAnswer(invocation -> {
            assertTrue(invocation.<List<?>>getArgument(1).isEmpty(), "LiLi is offered no native tools");
            prompts.add(invocation.getArgument(0));
            outputs.add(invocation.getArgument(2));
            return LlmTurn.builder().content(queue.remove(0)).build();
        });
    }

    private String decision(String branch, String intent, String query, String emotion, String message, List<String> choices) {
        return decision(branch, intent, query, List.of(), emotion, message, choices);
    }

    private String decision(
            String branch,
            String intent,
            String query,
            List<Integer> excludePositions,
            String emotion,
            String message,
            List<String> choices
    ) {
        var node = mapper.createObjectNode().put("branch", branch).put("intent", intent).put("search_query", query);
        var positions = node.putArray("exclude_positions");
        excludePositions.forEach(positions::add);
        node.put("emotion", emotion).put("message", message);
        choices.forEach(node.putArray("choices")::add);
        if (choices.isEmpty()) node.putArray("choices");
        return node.toString();
    }

    private String reply(String intent, String emotion, String message, List<String> choices) {
        var node = mapper.createObjectNode().put("intent", intent).put("emotion", emotion).put("message", message);
        var array = node.putArray("choices");
        choices.forEach(array::add);
        return node.toString();
    }

    private ConversationTool recording(LlmTurn.ToolDefinition definition, List<ConversationTool.Invocation> calls, ResultType type) {
        return new ConversationTool() {
            @Override
            public LlmTurn.ToolDefinition definition() {
                return definition;
            }

            @Override
            public Result execute(Invocation invocation) {
                calls.add(invocation);
                JsonNode data = new ObjectMapper().createObjectNode().put("jobId", UUID.randomUUID().toString())
                        .put("status", jobStatus).put("errorMessage", "FAILED".equals(jobStatus) ? FAILURE_REASON : null);
                return Result.builder().type(type).publicData(data).modelData(data).sources(Map.of()).build();
            }
        };
    }
}
