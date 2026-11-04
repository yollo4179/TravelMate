package com.yollo.TravelMate;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.config.observability.SearchTracing;
import com.yollo.TravelMate.domain.place.client.PlaceSemanticSearchClient;
import com.yollo.TravelMate.domain.place.data.response.PlaceSearchResponseDto;
import com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult;
import com.yollo.TravelMate.domain.place.data.result.SearchEvidenceChunk;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.repository.ContextPlanRepository;
import com.yollo.TravelMate.domain.plan.repository.PlanningJobRepository;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import com.yollo.TravelMate.domain.plan.validator.ContextPlanResultValidator;
import com.yollo.TravelMate.domain.plan.validator.PlanEvidenceCitationValidator;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.TransactionTemplate;
import static com.yollo.TravelMate.SearchEvidenceFixtures.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class SearchEvidencePipelineTest {
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();

    @SuppressWarnings("unchecked")
    List<PlaceSemanticSearchResult> consume(ObjectNode event) {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);
        TransactionTemplate transaction = mock(TransactionTemplate.class);
        doAnswer(invocation -> {
            invocation.<Consumer<TransactionStatus>>getArgument(0).accept(mock(TransactionStatus.class));
            return null;
        }).when(transaction).executeWithoutResult(any());
        var client = new PlaceSemanticSearchClient(jdbc, mapper, transaction, mock(SearchTracing.class), "mock-topic", 120);
        var pending = (Map<UUID, CompletableFuture<List<PlaceSemanticSearchResult>>>) ReflectionTestUtils.getField(client, "pendingRequests");
        var future = new CompletableFuture<List<PlaceSemanticSearchResult>>();
        pending.put(UUID.fromString(event.get("request_id").textValue()), future);
        client.receiveResult(event.toString());
        assertTrue(future.isDone(), "실제 Kafka 소비기가 파싱한 결과를 대기 요청에 전달해야 한다");
        return future.join();
    }

    private GeneratePlanRequest request() throws Exception {
        return mapper.readValue(PlanContextContractTest.REQUEST, GeneratePlanRequest.class);
    }

    @Test
    void kafkaToSearchDtoPreservesExactEvidenceAndScores() throws Exception {
        ObjectNode event = event(mapper);
        ObjectNode second = ((ObjectNode) event.path("items").get(0)).deepCopy();
        second.put("place_id", 202).put("rank", 2).put("name", "B공원").put("rerank_score", 0.1);
        ((ArrayNode) event.get("items")).add(second);
        var results = consume(event);
        assertEquals(List.of(101L, 202L), results.stream().map(result -> result.place().id()).toList());
        var result = results.get(0);
        JsonNode serialized = mapper.valueToTree(PlaceSearchResponseDto.from(result));
        assertEquals(event.path("items").get(0).get("evidence_chunks"), serialized.get("evidenceChunks"));
        assertEquals(101, serialized.get("placeId").asLong());
        assertEquals(0.8f, result.rerankScore());
        assertEquals(0.9, result.place().similarity());
        ObjectNode detached = (ObjectNode) result.evidenceChunks().get(0).toJson();
        detached.put("chunk_text", "외부 변경");
        assertEquals(ORIGINAL, result.evidenceChunks().get(0).toJson().get("chunk_text").textValue());
        var roundTrip = mapper.readValue(mapper.writeValueAsString(result.evidenceChunks().get(0)), SearchEvidenceChunk.class);
        assertEquals(result.evidenceChunks().get(0).toJson(), roundTrip.toJson());
    }

    @Test
    void promptKeepsFullOriginalPastNegationAndConflictingRecordBeyondDescriptionLimit() throws Exception {
        var results = consume(event(mapper));
        var prepared = new ContextPlanPromptFactory(mapper).prepare(request(), List.of(results.get(0).place()), results);
        JsonNode candidate = mapper.readTree(prepared.userPrompt().substring(prepared.userPrompt().indexOf('{'))).path("candidates").get(0);
        assertEquals(400, candidate.get("description").textValue().length());
        assertFalse(candidate.get("description").textValue().contains("현재도 통행"));
        JsonNode first = candidate.get("selectedEvidence").get(0);
        assertEquals(ORIGINAL, first.path("original").path("chunk_text").textValue());
        assertEquals(SUPPLEMENT, first.path("generatedSupplement").path("context_text").textValue());
        assertFalse(first.path("original").has("context_text"));
        assertEquals(results.get(0).evidenceChunks().get(0).toJson().get("relations"), first.path("annotations").get("relations"));
        assertEquals(BLOCK, candidate.path("selectedEvidence").get(1).path("original").get("chunk_text").textValue());
        assertEquals("SELECTED_UNASSESSED", candidate.get("evidenceAvailability").textValue());
        assertEquals(2, prepared.sources().size());
    }

    @Test
    void malformedQuoteOffsetsAndForeignMatchedRelationAreRejected() {
        ObjectNode valid = chunk(mapper, ORIGINAL, WALK);
        assertDoesNotThrow(() -> new SearchEvidenceChunk(valid));
        ObjectNode changed = valid.deepCopy();
        ((ObjectNode) changed.path("relations").get(0).get("evidence")).put("quote", "원문에 없는 인용");
        assertThrows(IllegalArgumentException.class, () -> new SearchEvidenceChunk(changed));
        ObjectNode wrongOffset = valid.deepCopy();
        ((ObjectNode) wrongOffset.path("relations").get(0).get("evidence")).put("start", 0);
        assertThrows(IllegalArgumentException.class, () -> new SearchEvidenceChunk(wrongOffset));
        ObjectNode foreign = valid.deepCopy();
        foreign.putArray("matched_relations").addObject().put("type", "invented");
        assertThrows(IllegalArgumentException.class, () -> new SearchEvidenceChunk(foreign));
    }

    @Test
    void citationChecksMembershipNotSemanticTruth() throws Exception {
        var results = consume(event(mapper));
        var prompt = new ContextPlanPromptFactory(mapper).prepare(request(), List.of(results.get(0).place()), results);
        String sourceId = results.get(0).evidenceChunks().get(0).sourceId();
        var valid = new GeneratedPlan.SourceCitation("E101-0", sourceId, WALK);
        assertDoesNotThrow(() -> PlanEvidenceCitationValidator.validate(plan(101L, valid), prompt));
        for (var invalid : List.of(
                new GeneratedPlan.SourceCitation("E101-99", sourceId, WALK),
                new GeneratedPlan.SourceCitation("E101-0", "없는 출처", WALK),
                new GeneratedPlan.SourceCitation("E101-0", sourceId, SUPPLEMENT),
                new GeneratedPlan.SourceCitation("E101-0", sourceId, "걸어갈 수 있다.")
        )) {
            assertThrows(IllegalStateException.class, () -> PlanEvidenceCitationValidator.validate(plan(101L, invalid), prompt));
        }
        assertThrows(IllegalStateException.class, () -> PlanEvidenceCitationValidator.validate(plan(202L, valid), prompt));
        var unsupportedProse = new GeneratedPlan("초안", "의미 검증 대상", List.of(
                new GeneratedPlan.GeneratedPin(101L, 1, "활동", "이 문장의 의미는 이 검사가 판정하지 않는다", List.of(valid))));
        assertDoesNotThrow(() -> PlanEvidenceCitationValidator.validate(unsupportedProse, prompt));
    }

    @Test
    void relationEndpointCannotCiteTheOriginsSceneryAsItsOwnObservation() throws Exception {
        ObjectNode original = chunk(mapper, ORIGINAL, WALK);
        original.put("retrieval_scope", "relation").put("retrieved_relation_index", 0);
        original.putArray("matched_relations").add(original.path("relations").get(0).deepCopy());
        var selected = new SearchEvidenceChunk(original);
        assertTrue(selected.permitsQuote(202, WALK));
        assertFalse(selected.permitsQuote(202, "A공원의 야경을 봤다는 방문 기록."));
        assertEquals(original, selected.toJson());
    }

    @Test
    void legacyAndRequiredPlacesDoNotAcquireInventedEvidence() throws Exception {
        ObjectNode event = event(mapper);
        ((ObjectNode) event.path("items").get(0)).remove("evidence_chunks");
        var results = consume(event);
        assertTrue(results.get(0).evidenceChunks().isEmpty());
        var prepared = new ContextPlanPromptFactory(mapper).prepare(request(), List.of(results.get(0).place()), results);
        assertTrue(prepared.sources().isEmpty());
        assertTrue(prepared.userPrompt().contains("NONE_SELECTED"));
        PlanEvidenceCitationValidator.validate(new GeneratedPlan("초안", "근거 부족", List.of(
                new GeneratedPlan.GeneratedPin(101L, 1, "방문", "근거 부족"))), prepared);
    }

    @Test
    void actualPlanningServicePassesKafkaEvidenceToExistingLlmAndKeepsSavePayload() throws Exception {
        var results = consume(event(mapper));
        var jobs = mock(PlanningJobRepository.class);
        var plans = mock(ContextPlanRepository.class);
        var search = mock(PlaceSemanticSearchService.class);
        var llm = mock(LlmClient.class);
        var input = request();
        when(plans.requiredPlaces(List.of(101L))).thenReturn(List.of(results.get(0).place()));
        when(plans.save(anyString(), any(), any(), anyList(), anyString())).thenReturn(77L);
        when(search.search(anyString(), isNull(), isNull(), isNull(), eq(9), eq(input.context().area()))).thenReturn(results);
        var citation = new GeneratedPlan.SourceCitation("E101-0", results.get(0).evidenceChunks().get(0).sourceId(), WALK);
        when(llm.generate(anyString(), anyString())).thenReturn(mapper.writeValueAsString(plan(101L, citation)));
        var service = new ContextPlanningService(jobs, plans, search, mapper, llm,
                new ContextPlanResultValidator(mapper), new ContextPlanPromptFactory(mapper));
        UUID jobId = UUID.randomUUID();
        try {
            ReflectionTestUtils.invokeMethod(service, "runGeneration", jobId, "mock-user", input, "original-request");
            var prompt = ArgumentCaptor.forClass(String.class);
            verify(llm).generate(contains("generatedSupplement"), prompt.capture());
            assertTrue(prompt.getValue().contains(mapper.writeValueAsString(ORIGINAL)));
            assertTrue(prompt.getValue().contains(BLOCK));
            var saved = ArgumentCaptor.forClass(GeneratedPlan.class);
            verify(plans).save(eq("mock-user"), eq(input), saved.capture(), eq(List.of(results.get(0).place())), eq("original-request"));
            assertEquals(101L, saved.getValue().pins().get(0).placeId());
            assertEquals(1, saved.getValue().pins().get(0).sequence());
            verify(jobs).update(jobId, PlanningResponse.JobStatus.SUCCEEDED, 77L, null);

            // A citation naming a source that was never delivered loses its mark; the rest of the draft is still saved.
            when(llm.generate(anyString(), anyString())).thenReturn(mapper.writeValueAsString(plan(101L,
                    new GeneratedPlan.SourceCitation("E101-0", "없는 출처", WALK))));
            clearInvocations(plans, jobs);
            UUID droppedJob = UUID.randomUUID();
            ReflectionTestUtils.invokeMethod(service, "runGeneration", droppedJob, "mock-user", input, "original-request");
            verify(plans).save(eq("mock-user"), eq(input), any(), eq(List.of(results.get(0).place())), eq("original-request"));
            verify(jobs).update(droppedJob, PlanningResponse.JobStatus.SUCCEEDED, 77L, null);
        } finally {
            ReflectionTestUtils.invokeMethod(service, "shutdown");
        }
    }

    private GeneratedPlan plan(Long placeId, GeneratedPlan.SourceCitation citation) {
        return new GeneratedPlan("초안", "근거 설명", List.of(
                new GeneratedPlan.GeneratedPin(placeId, 1, "방문", "원문 기록 참조", List.of(citation))));
    }
}
