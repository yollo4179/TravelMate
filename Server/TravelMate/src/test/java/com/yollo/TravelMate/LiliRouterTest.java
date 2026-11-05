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
import com.yollo.TravelMate.domain.place.data.internal.Sido;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchContext;
import com.yollo.TravelMate.domain.place.data.result.PlaceCoverage;
import com.yollo.TravelMate.domain.place.service.PlaceCoverageService;
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
    private JsonNode storedReaction;
    private String requestedRegion;
    private final PlaceCoverageService coverage = mock(PlaceCoverageService.class);
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
                new LiliJobHandler(actions, renderer, mapper)), renderer, mapper,
                coverage, new PlaceCoverageGate(coverage, renderer, mapper));
        when(coverage.current()).thenReturn(new PlaceCoverage(List.of(Sido.SEOUL), List.of("관광지")));
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
        // fx runs: with no list sent, LiLi still offered position, name and "show the list" choices that cannot work.
        assertTrue(system.contains("displayedResultCount가 0이면 앱이 목록을 보내지 않은 것이라 어떤 순번도 고를 수 없다"));
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

    // Live runs: LiLi told users to switch the search to Busan or Jeju, which the place data does not hold.
    @Test
    void anAreaThePlaceDataDoesNotHoldEndsWithTheCoverageLineAndNoSearch() throws Exception {
        requestedRegion = "부산";
        answer(decision("SEARCH_PLACES", "RECOMMENDATION", "부산 해운대 관광지", "EXCITED", "해운대 쪽으로 찾아볼게!", List.of()));
        var response = respond(new ConversationRequest("부산 해운대 근처 관광지 알려줘.", null, List.of()));
        verifyNoInteractions(recommendations);
        assertEquals(ResultType.TEXT, response.type());
        assertEquals(List.of(LiliFixedLines.outsideCoverage("부산", "서울", "관광지")), response.dialogue(),
                "her promise to look in Busan is replaced, not shown");
        assertTrue(response.message().contains("서울 관광지만"));
        assertTrue(lastUserInput(0).contains("\"searchCoverage\":{\"regions\":[\"서울\"],\"categories\":[\"관광지\"]}"));
    }

    @Test
    void askingBackAboutAnAreaOutsideTheDataGetsTheSameLine() throws Exception {
        requestedRegion = "제주";
        answer(decision("CLARIFY", "RECOMMENDATION", null, "THINKING", "제주로 범위를 바꿔서 다시 물어봐 줄래?",
                List.of("제주로 범위 바꾸기", "서울에서 찾기")));
        var response = respond(new ConversationRequest("성산일출봉 쪽 볼거리 추천해줘.", null, List.of()));
        assertEquals(List.of(LiliFixedLines.outsideCoverage("제주", "서울", "관광지")), response.dialogue());
        assertTrue(response.choices().isEmpty(), "no choice leads to an area the data does not hold");
    }

    @Test
    void anAreaTheDataHoldsIsSearchedAsBefore() throws Exception {
        requestedRegion = "서울";
        answer(decision("SEARCH_PLACES", "RECOMMENDATION", QUERY, "EXCITED", "찾아볼게!", List.of()));
        respond(new ConversationRequest("종로 궁궐 추천해줘.", null, List.of()));
        verify(recommendations).submit(eq(OWNER), any(), any(), eq(QUERY));
    }

    @Test
    void unknownCoverageNeverRefusesASearch() throws Exception {
        when(coverage.current()).thenReturn(PlaceCoverage.UNKNOWN);
        requestedRegion = "부산";
        answer(decision("SEARCH_PLACES", "RECOMMENDATION", "부산 해운대 관광지", "EXCITED", "찾아볼게!", List.of()));
        respond(new ConversationRequest("부산 해운대 근처 관광지 알려줘.", null, List.of()));
        verify(recommendations).submit(eq(OWNER), any(), any(), eq("부산 해운대 관광지"));
        assertFalse(lastUserInput(0).contains("searchCoverage"), "she is not told a range the server could not read");
    }

    @Test
    void smallTalkThatNamesAnAreaStaysSmallTalk() throws Exception {
        requestedRegion = "부산";
        answer(decision("CHAT", "CONVERSATION", null, "HAPPY", "부산 다녀왔구나, 좋았겠다!", List.of()));
        var response = respond(new ConversationRequest("나 지난주에 부산 다녀왔어!", null, List.of()));
        assertEquals("부산 다녀왔구나, 좋았겠다!", response.message());
    }

    @Test
    void theRouterNoLongerAsksBackOnARegionBeforeSearching() throws Exception {
        answer(decision("CHAT", "CONVERSATION", null, "HAPPY", "안녕!", List.of()));
        respond(new ConversationRequest("안녕", null, List.of()));
        String system = prompts.get(0).get(0).content();
        assertFalse(system.contains("필터와 충돌하면"), "the rule that skipped searches in live runs is gone");
        assertTrue(system.contains("searchCoverage"));
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
                reply("PLAN", "THINKING", "앱에서 일정 조건을 입력한 뒤 요청해 줘.", List.of("조건 입력 후 요청하기", "장소 추천받기")));
        var response = respond(new ConversationRequest("다음 주 토요일 오전 10시부터 12시까지, 출발은 종로3가역이야.", null,
                List.of(new ConversationRequest.HistoryMessage(ConversationRequest.HistoryRole.USER, "서울 여행 일정을 만들어줘."))));
        assertTrue(planInvocations.isEmpty());
        assertEquals("앱에서 일정 조건을 입력한 뒤 요청해 줘.", response.message());
        assertEquals(LiliTurnContract.REPLY_NAME, outputs.get(1).name());
        String followUp = lastUserInput(1);
        assertTrue(followUp.contains(LiliServerCode.PLANNING_CONDITIONS_MISSING.situation()));
        assertFalse(followUp.contains(LiliServerCode.PLANNING_CONDITIONS_MISSING.name()), "LiLi never reads an internal code");
        assertTrue(followUp.contains("대화로 받은 날짜·시간·출발지는 일정 입력으로 자동 반영되지 않는다"));
        assertTrue(prompts.get(0).get(0).content().contains("말로 빠진 조건을 수집하지 않는다"));
    }

    // Live core run: with no job ID in the message the router still chose the job lookup; now it cannot.
    @Test
    void theJobLookupIsOfferedOnlyWhenTheMessageCarriesAJobId() throws Exception {
        answer(decision("CLARIFY", "PLAN", null, "THINKING", "어떤 작업인지 번호를 알려줄래?", List.of("작업 번호 알려주기", "새 일정 만들기")),
                decision("GET_PLANNING_JOB", "PLAN", null, "THINKING", "확인해 볼게.", List.of()));
        respond(new ConversationRequest("내 일정 생성 작업이 어디까지 됐어?", null, List.of()));
        respond(new ConversationRequest("작업 " + UUID.randomUUID() + " 어떻게 됐어?", null, List.of()));
        assertFalse(branchChoices(0).contains("GET_PLANNING_JOB"), "no ID, so the lookup is not a choice");
        assertTrue(branchChoices(0).contains("CLARIFY"));
        assertTrue(branchChoices(1).contains("GET_PLANNING_JOB"));
    }

    @Test
    void bookingOrConfirmingIsAMissingFeatureEvenWhenATripIsMentioned() throws Exception {
        answer(decision("CHAT", "CONVERSATION", null, "THINKING", "예약은 내가 못 해.", List.of()));
        respond(new ConversationRequest("안녕", null, List.of()));
        String system = prompts.get(0).get(0).content();
        assertTrue(system.contains("예약·결제·확정을 해 달라는 요청은 일정 이야기가 함께 있어도 지원하지 않는 기능 요청이다"));
    }

    private List<String> branchChoices(int call) {
        var choices = new ArrayList<String>();
        outputs.get(call).schema().path("properties").path("branch").path("enum").forEach(value -> choices.add(value.asText()));
        return choices;
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

    // The draft job stored LiLi's reaction when it failed; asking her again would cost a call and lose what was searched.
    @Test
    void failedJobWithAStoredReactionIsToldInThoseCutsWithoutAFollowUpCall() throws Exception {
        jobStatus = "FAILED";
        storedReaction = mapper.readTree("""
                [{"text":"종로 범위를 다 찾아봤는데 넣을 곳이 없었어.","emotion":"SAD"}]""");
        String jobId = UUID.randomUUID().toString();
        answer(decision("GET_PLANNING_JOB", "PLAN", null, "THINKING", "확인해 볼게.", List.of()));
        var response = respond(new ConversationRequest("작업 " + jobId + " 어떻게 됐어?", null, List.of()));
        assertEquals(List.of(new DialogueCut("확인해 볼게.", CharacterEmotion.THINKING),
                new DialogueCut("종로 범위를 다 찾아봤는데 넣을 곳이 없었어.", CharacterEmotion.SAD)), response.dialogue());
        assertEquals(1, outputs.size(), "the stored reaction needs no second model call");
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
        assertEquals(List.of("branch", "intent", "search_query", "requested_region", "exclude_positions", "emotion", "message", "choices"), order);
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
        var node = mapper.createObjectNode().put("branch", branch).put("intent", intent).put("search_query", query)
                .put("requested_region", requestedRegion);
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
                var data = new ObjectMapper().createObjectNode().put("jobId", UUID.randomUUID().toString())
                        .put("status", jobStatus).put("errorMessage", "FAILED".equals(jobStatus) ? FAILURE_REASON : null);
                data.set("dialogue", storedReaction);
                return Result.builder().type(type).publicData(data).modelData(data).sources(Map.of()).build();
            }
        };
    }
}
