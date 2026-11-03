package com.yollo.TravelMate;

import java.util.List;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.domain.conversation.data.*;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.*;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.place.data.response.PlaceSearchResponseDto;
import com.yollo.TravelMate.domain.place.data.result.*;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import static com.yollo.TravelMate.SearchEvidenceFixtures.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ConversationToolLoopTest {
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();
    private final ContextPlanningService planning = mock(ContextPlanningService.class);
    private final PlaceSemanticSearchService searches = mock(PlaceSemanticSearchService.class);
    private final LlmClient llm = mock(LlmClient.class);
    private final UUID jobId = UUID.randomUUID();

    @Test
    void actualToolLoopReturnsExactServerDataAndGroundsExplanationInSelectedOriginals() throws Exception {
        var result = searchResult();
        when(searches.search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class))).thenReturn(List.of(result));
        AtomicInteger turns = new AtomicInteger();
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            List<LlmMessage> history = invocation.getArgument(0);
            if (turns.getAndIncrement() == 0) {
                List<LlmTurn.ToolDefinition> definitions = invocation.getArgument(1);
                assertEquals(List.of("generate_plan", "get_planning_job", "search_places"),
                        definitions.stream().map(LlmTurn.ToolDefinition::name).toList());
                return call("search-1", "search_places", "{\"query\":\"야경과 연결\",\"limit\":5}");
            }
            assertEquals(LlmMessage.Role.ASSISTANT, history.get(history.size() - 2).role());
            assertEquals("search-1", history.get(history.size() - 1).toolCallId());
            JsonNode grounded = mapper.readTree(history.get(history.size() - 1).content()).path("data").path("candidates").get(0);
            assertEquals(ORIGINAL, grounded.path("selectedEvidence").get(0).path("original").path("chunk_text").asText());
            assertEquals(SUPPLEMENT, grounded.path("selectedEvidence").get(0).path("generatedSupplement").path("context_text").asText());
            assertEquals(BLOCK, grounded.path("selectedEvidence").get(1).path("original").path("chunk_text").asText());
            assertEquals(result.evidenceChunks().get(0).toJson().path("relations"),
                    grounded.path("selectedEvidence").get(0).path("annotations").path("relations"));
            String evidenceId = grounded.path("selectedEvidence").get(0).path("evidenceId").asText();
            return answer("과거 이동 경험과 공사 차단 기록이 함께 있어 현재 통행 여부는 확인이 필요합니다.", List.of(
                    new Citation(101L, evidenceId, result.evidenceChunks().get(0).sourceId(), WALK)));
        });
        var response = service(6, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(ResultType.PLACES, response.type());
        assertEquals(Termination.COMPLETED, response.termination());
        assertEquals(mapper.valueToTree(List.of(PlaceSearchResponseDto.from(result))), response.data());
        assertEquals(1, response.citations().size());
        assertEquals(2, response.modelTurns());
        verify(searches).search(argThat(criteria -> criteria.query().equals("야경과 연결") && criteria.limit() == 5));
    }

    @ParameterizedTest
    @ValueSource(strings = {"wrong-place", "wrong-source", "invented-id", "supplement", "negation-rewrite"})
    void citationMembershipRejectsForeignSourcesAttributionAndInventedQuotes(String defect) throws Exception {
        var result = searchResult();
        when(searches.search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class))).thenReturn(List.of(result));
        AtomicInteger turns = new AtomicInteger();
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> {
            if (turns.getAndIncrement() == 0) return call("s1", "search_places", "{\"query\":\"연결\",\"limit\":5}");
            List<LlmMessage> history = invocation.getArgument(0);
            String evidenceId = mapper.readTree(history.get(history.size() - 1).content())
                    .path("data").path("candidates").get(0).path("selectedEvidence").get(0).path("evidenceId").asText();
            return answer("확인한 설명", List.of(new Citation(
                    defect.equals("wrong-place") ? 202L : 101L,
                    defect.equals("invented-id") ? "invented" : evidenceId,
                    defect.equals("wrong-source") ? "foreign" : result.evidenceChunks().get(0).sourceId(),
                    defect.equals("supplement") ? SUPPLEMENT : defect.equals("negation-rewrite") ? "걸어갈 수 있다." : WALK
            )));
        });
        var response = service(6, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(Termination.INVALID_RESPONSE, response.termination());
        assertEquals(ResultType.PLACES, response.type());
        assertTrue(response.citations().isEmpty());
        assertEquals(mapper.valueToTree(List.of(PlaceSearchResponseDto.from(result))), response.data());
    }

    @Test
    void modelCannotReplaceServerPlaceOrPlanDataInFinalJson() throws Exception {
        when(searches.search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class))).thenReturn(List.of(searchResult()));
        when(llm.chat(anyList(), anyList())).thenReturn(
                call("s1", "search_places", "{\"query\":\"연결\",\"limit\":5}"),
                LlmTurn.builder().content("{\"message\":\"설명\",\"citations\":[],\"type\":\"DRAFT\",\"data\":{\"planId\":999}}").build()
        );
        var response = service(6, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(Termination.INVALID_RESPONSE, response.termination());
        assertEquals(ResultType.PLACES, response.type());
        assertEquals(101L, response.data().get(0).path("placeId").asLong());
        verify(planning, never()).generate(anyString(), any(), any());
    }

    @ParameterizedTest
    @EnumSource(value = PlanningResponse.JobStatus.class, names = {"QUEUED", "RUNNING", "FAILED"})
    void aJobReceiptNeverBecomesACompletedDraftThroughModelProse(PlanningResponse.JobStatus status) throws Exception {
        when(planning.generate(anyString(), any(), any())).thenReturn(job(status, null));
        when(llm.chat(anyList(), anyList())).thenReturn(
                call("g1", "generate_plan", "{}"), answer("일정이 확정되고 완성됐습니다!", List.of()));
        var response = service(6, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(ResultType.PLANNING_JOB, response.type());
        assertEquals(status.name(), response.data().get("status").asText());
        assertFalse(response.message().contains("확정되고"));
        assertFalse(response.message().contains("완성됐습니다"));
        verify(planning, never()).plan(anyLong(), anyString());
    }

    @Test
    void repeatedGenerationIsCachedAndAPlanningReceiptRemainsPrimaryAfterLaterSearch() throws Exception {
        when(planning.generate(anyString(), any(), any())).thenReturn(job(PlanningResponse.JobStatus.QUEUED, null));
        when(searches.search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class))).thenReturn(List.of(searchResult()));
        when(llm.chat(anyList(), anyList())).thenReturn(
                call("g1", "generate_plan", "{}"),
                call("g2", "generate_plan", "{}"),
                call("s1", "search_places", "{\"query\":\"야경\",\"limit\":5}"),
                answer("검색도 했습니다.", List.of()));
        var request = request();
        var turnKey = UUID.randomUUID();
        var response = service(6, 8).respond("owner", turnKey, request);
        assertEquals(ResultType.PLANNING_JOB, response.type());
        assertEquals(jobId.toString(), response.data().get("jobId").asText());
        assertEquals(ToolStatus.CACHED, response.toolResults().get(1).status());
        verify(planning).generate(eq("owner"), any(), eq(request.planningRequest()));
        when(llm.chat(anyList(), anyList())).thenReturn(
                call("g3", "generate_plan", "{}"), answer("생성 접수", List.of()));
        service(6, 8).respond("owner", turnKey, request);
        var generationKeys = ArgumentCaptor.forClass(UUID.class);
        verify(planning, times(2)).generate(eq("owner"), generationKeys.capture(), eq(request.planningRequest()));
        assertEquals(generationKeys.getAllValues().get(0), generationKeys.getAllValues().get(1));
        assertNotEquals(turnKey, generationKeys.getValue());
    }

    @Test
    void ownedSucceededJobReturnsOnlyTheDraftActuallyReadFromTheServer() throws Exception {
        when(planning.job(jobId, "owner")).thenReturn(job(PlanningResponse.JobStatus.SUCCEEDED, 77L));
        var draft = new PlanningResponse.Draft(
                77L,
                request().planningRequest().context(),
                "서버 초안",
                List.of(new PlanningResponse.Pin(101L, "A공원", 35.8395, 129.212, 60, 1)),
                List.of("운영시간과 실제 이동 경로 미검증")
        );
        when(planning.plan(77L, "owner")).thenReturn(draft);
        when(llm.chat(anyList(), anyList())).thenReturn(
                call("j1", "get_planning_job", "{\"job_id\":\"" + jobId + "\"}"),
                answer("서버가 반환한 초안입니다.", List.of()));
        var response = service(6, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(ResultType.DRAFT, response.type());
        assertEquals(mapper.valueToTree(draft), response.data());
        verify(planning).job(jobId, "owner");
        verify(planning).plan(77L, "owner");
    }

    @Test
    void ownershipFailureIsReturnedAsAToolErrorWithoutLoadingADraft() throws Exception {
        when(planning.job(jobId, "other-owner")).thenThrow(new ResponseStatusException(HttpStatus.NOT_FOUND));
        when(llm.chat(anyList(), anyList())).thenReturn(
                call("j1", "get_planning_job", "{\"job_id\":\"" + jobId + "\"}"),
                answer("작업을 확인할 수 없습니다.", List.of()));
        var response = service(6, 8).respond("other-owner", UUID.randomUUID(), request());
        assertEquals(ResultType.ERROR, response.type());
        assertEquals(ToolStatus.FAILED, response.toolResults().get(0).status());
        verify(planning, never()).plan(anyLong(), anyString());
    }

    @ParameterizedTest
    @ValueSource(strings = {"modify_plan", "rollback_plan", "not_registered"})
    void unavailableToolsAreNeverRegisteredOrExecuted(String name) throws Exception {
        when(llm.chat(anyList(), anyList())).thenReturn(call("x1", name, "{}"), answer("지원하지 않는 작업입니다.", List.of()));
        var response = service(6, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(ResultType.ERROR, response.type());
        assertEquals(ToolStatus.FAILED, response.toolResults().get(0).status());
        verifyNoInteractions(planning);
    }

    @ParameterizedTest
    @ValueSource(strings = {"[]", "{", "{\"query\":\"야경\",\"limit\":5,\"userUid\":\"victim\"}",
            "{\"query\":\"야경\",\"limit\":21}", "{\"query\":\"야경\",\"limit\":5} {}"})
    void malformedOrExtraArgumentsCannotReachTheSearchService(String arguments) throws Exception {
        when(llm.chat(anyList(), anyList())).thenReturn(call("x1", "search_places", arguments), answer("검색 조건을 확인해 주세요.", List.of()));
        var response = service(6, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(ToolStatus.FAILED, response.toolResults().get(0).status());
        verifyNoInteractions(planning);
    }

    @Test
    void modelAndToolLimitsStopLoopsAndPreserveAlreadyObservedServerResults() throws Exception {
        when(searches.search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class))).thenReturn(List.of(searchResult()));
        AtomicInteger turns = new AtomicInteger();
        when(llm.chat(anyList(), anyList())).thenAnswer(invocation -> call(
                "s" + turns.incrementAndGet(), "search_places", turns.get() % 2 == 0
                        ? "{\"limit\":5,\"query\":\"야경\"}" : "{\"query\":\"야경\",\"limit\":5}"));
        var response = service(3, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(Termination.MODEL_LIMIT, response.termination());
        assertEquals(ResultType.PLACES, response.type());
        assertEquals(3, response.modelTurns());
        verify(searches).search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class));
        assertEquals(ToolStatus.CACHED, response.toolResults().get(2).status());
        clearInvocations(searches);
        var limited = service(6, 1).respond("owner", UUID.randomUUID(), request());
        assertEquals(Termination.TOOL_LIMIT, limited.termination());
        assertEquals(1, limited.toolResults().size());
        verify(searches).search(any(com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest.class));
    }

    @Test
    void modelFailureAfterToolExecutionRetainsTheReceiptWithoutRetryingOrRegenerating() throws Exception {
        when(planning.generate(anyString(), any(), any())).thenReturn(job(PlanningResponse.JobStatus.QUEUED, null));
        when(llm.chat(anyList(), anyList())).thenReturn(call("g1", "generate_plan", "{}"))
                .thenThrow(new IllegalStateException("provider failed"));
        var response = service(6, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(Termination.MODEL_FAILED, response.termination());
        assertEquals(ResultType.PLANNING_JOB, response.type());
        assertEquals(jobId.toString(), response.data().get("jobId").asText());
        verify(planning).generate(anyString(), any(), any());
        verify(llm, times(2)).chat(anyList(), anyList());
    }

    @Test
    void duplicateCallIdsRejectTheWholeBatchBeforeAnySideEffects() throws Exception {
        var duplicate = new LlmTurn.ToolCall("same", "generate_plan", "{}");
        when(llm.chat(anyList(), anyList())).thenReturn(LlmTurn.builder().toolCalls(List.of(duplicate, duplicate)).build());
        var response = service(6, 8).respond("owner", UUID.randomUUID(), request());
        assertEquals(Termination.INVALID_RESPONSE, response.termination());
        assertTrue(response.toolResults().isEmpty());
        verifyNoInteractions(planning);
    }

    private ConversationService service(int modelTurns, int toolCalls) {
        var resultMapper = new PlanningToolResults(planning, mapper);
        var registry = new ConversationToolRegistry(List.of(
                new SearchPlacesTool(searches, new PlaceSearchCriteriaResolver(), new ContextPlanPromptFactory(mapper), mapper),
                new GeneratePlanTool(planning, resultMapper),
                new GetPlanningJobTool(planning, resultMapper)
        ));
        return new ConversationService(
                llm,
                registry,
                new ConversationToolExecutor(registry, mapper),
                new ConversationAnswerRenderer(mapper),
                mapper,
                modelTurns,
                toolCalls
        );
    }

    private ConversationRequest request() throws Exception {
        return new ConversationRequest(
                "야경 보고 다른 관광지와 연결된 곳을 찾고 초안을 만들어 줘",
                mapper.readValue(PlanContextContractTest.REQUEST, GeneratePlanRequest.class),
                List.of()
        );
    }

    private PlanningResponse.Job job(PlanningResponse.JobStatus status, Long planId) {
        return new PlanningResponse.Job(jobId, status, "/api/v1/planning-jobs/" + jobId, planId, null);
    }

    private LlmTurn call(String id, String name, String arguments) {
        return LlmTurn.builder().content("{\"afterTool\":\"REASSESS\"}")
                .toolCalls(List.of(new LlmTurn.ToolCall(id, name, arguments))).build();
    }

    private LlmTurn answer(String message, List<Citation> citations) {
        ObjectNode payload = mapper.createObjectNode().put("message", message);
        payload.set("citations", mapper.valueToTree(citations));
        return LlmTurn.builder().content(payload.toString()).build();
    }

    private PlaceSemanticSearchResult searchResult() throws Exception {
        var place = mapper.readValue("""
                {"id":101,"name":"A공원","description":"요약","category":"카페",
                 "latitude":35.8395,"longitude":129.212,"similarity":0.9}
                """, PlaceResult.class);
        return new PlaceSemanticSearchResult(place, 0.8f, List.of(
                new SearchEvidenceChunk(chunk(mapper, ORIGINAL, WALK)),
                new SearchEvidenceChunk(chunk(mapper, BLOCK, BLOCK))
        ));
    }
}
