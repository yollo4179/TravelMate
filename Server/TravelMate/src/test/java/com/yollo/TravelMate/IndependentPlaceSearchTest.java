package com.yollo.TravelMate;

import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.config.observability.SearchTracing;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.place.client.PlaceSemanticSearchClient;
import com.yollo.TravelMate.domain.place.controller.PlaceSearchController;
import com.yollo.TravelMate.domain.place.data.request.*;
import com.yollo.TravelMate.domain.place.data.result.*;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService.RankingMode;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.budget.*;
import com.yollo.TravelMate.ai.llm.derived.OllamaLlmClient;
import com.yollo.TravelMate.domain.conversation.service.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.support.TransactionTemplate;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static com.yollo.TravelMate.SearchEvidenceFixtures.*;

class IndependentPlaceSearchTest {
    private final JsonMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();
    private final PlaceSearchCriteriaResolver resolver = new PlaceSearchCriteriaResolver();

    @Test
    void captureBothCurrentNativeRequestsForTheFourProposedCasesWithoutCallingAnyProvider() throws Exception {
        Set<String> selectedIds = Set.of("PLR-TM-palaces-01", "PLR-TM-palaces-03", "PLR-TM-palaces-04", "PLR-TM-family_parks-04");
        var mappings = Files.readAllLines(Path.of("../../Evaluation/runs/contextual/exact-qwen-and-search-contract-v1/20261102-01/search-case-mapping.jsonl"));
        List<String> captured = new ArrayList<>();
        for (String line : mappings) {
            JsonNode binding = mapper.readTree(line);
            if (!selectedIds.contains(binding.path("case_id").asText())) continue;
            var criteria = mapper.treeToValue(binding.path("proposed_search_request"), PlaceSearchRequest.class);
            var context = new PlaceSearchContext(criteria.region(), criteria.city(), criteria.category(), criteria.excludePlaceIds(), criteria.area());
            List<ConversationRequest.HistoryMessage> history = new ArrayList<>();
            for (JsonNode message : binding.path("conversation_history_once")) {
                history.add(new ConversationRequest.HistoryMessage(ConversationRequest.HistoryRole.valueOf(message.path("role").asText().toUpperCase()), message.path("content").asText()));
            }
            var request = new ConversationRequest(criteria.query(), null, history, context);
            var guard = mock(LlmCallGuard.class);
            AtomicInteger turns = new AtomicInteger();
            var rawArguments = mapper.createObjectNode().put("query", criteria.query()).put("limit", 10);
            rawArguments.putNull("region").putNull("city").putNull("category").putNull("area");
            rawArguments.putArray("exclude_place_ids");
            doAnswer(invocation -> {
                JsonNode wire = invocation.getArgument(1);
                int turn = turns.incrementAndGet();
                var row = mapper.createObjectNode().put("case_id", binding.path("case_id").asText())
                        .put("input_sha256", binding.path("input_sha256").asText()).put("mode", "MOCK")
                        .put("scope", turn == 1 ? "CURRENT_INITIAL" : "CURRENT_MOCK_TOOL_FOLLOWUP");
                row.set("wire", wire);
                captured.add(row.toString());
                if (turn == 1) return LlmTurn.builder().toolCalls(List.of(new LlmTurn.ToolCall("s1", "search_places", rawArguments.toString()))).build();
                return LlmTurn.builder().content("{\"message\":\"MOCK explanation\",\"citations\":[]}").build();
            }).when(guard).call(any(), any(), any(), any(), any(), any());
            var httpBuilder = org.springframework.web.client.RestClient.builder().baseUrl("http://never-call.invalid");
            var http = org.springframework.test.web.client.MockRestServiceServer.bindTo(httpBuilder).build();
            var llm = new OllamaLlmClient(httpBuilder.build(), "qwen3:8b", 8192, 1536, guard);
            var searches = mock(PlaceSemanticSearchService.class);
            var place = mapper.readValue("{\"id\":101,\"name\":\"MOCK A\"}", PlaceResult.class);
            when(searches.search(any(PlaceSearchRequest.class))).thenReturn(List.of(new PlaceSemanticSearchResult(place, .8f,
                    List.of(new SearchEvidenceChunk(chunk(mapper, ORIGINAL, WALK)), new SearchEvidenceChunk(chunk(mapper, BLOCK, BLOCK))))));
            var registry = new ConversationToolRegistry(List.of(new SearchPlacesTool(searches, resolver, new ContextPlanPromptFactory(mapper), mapper)), "SEARCH_PLACES");
            var conversation = new ConversationService(llm, registry, new ConversationToolExecutor(registry, mapper), new ConversationAnswerRenderer(mapper), mapper, 2, 1, ConversationService.ToolFailurePolicy.STOP);
            var response = conversation.respond("mock-owner", UUID.randomUUID(), request);
            assertEquals(com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination.COMPLETED, response.termination());
            verify(searches).search(criteria);
            http.verify();
        }
        assertEquals(8, captured.size());
        Path output = Path.of("build/independent-search");
        Files.createDirectories(output);
        Files.writeString(output.resolve("current-native-wires.jsonl"), String.join("\n", captured) + "\n");
    }

    @Test
    void evaluationConfigurationStopsUnsupportedToolsAndRepeatedOrMultipleSearchesBeforeEffects() throws Exception {
        for (String scenario : List.of("unsupported_plan", "multiple", "repeated")) {
            var searches = mock(PlaceSemanticSearchService.class);
            when(searches.search(any(PlaceSearchRequest.class))).thenReturn(List.of());
            var search = new SearchPlacesTool(searches, resolver, new ContextPlanPromptFactory(mapper), mapper);
            var registry = new ConversationToolRegistry(List.of(search), "SEARCH_PLACES");
            assertEquals(List.of("search_places"), registry.definitions().stream().map(LlmTurn.ToolDefinition::name).toList());
            var llm = mock(LlmClient.class);
            var call = new LlmTurn.ToolCall("s1", "search_places", "{\"query\":\"park\",\"limit\":10}");
            var first = scenario.equals("unsupported_plan")
                    ? List.of(new LlmTurn.ToolCall("g1", "generate_plan", "{}"))
                    : scenario.equals("multiple") ? List.of(call, new LlmTurn.ToolCall("s2", "search_places", call.arguments())) : List.of(call);
            when(llm.chat(anyList(), anyList())).thenReturn(LlmTurn.builder().toolCalls(first).build(),
                    LlmTurn.builder().toolCalls(List.of(new LlmTurn.ToolCall("s2", "search_places", call.arguments()))).build());
            var conversation = new ConversationService(llm, registry, new ConversationToolExecutor(registry, mapper), new ConversationAnswerRenderer(mapper), mapper, 2, 1, ConversationService.ToolFailurePolicy.STOP);
            var result = conversation.respond("mock-owner", UUID.randomUUID(), new ConversationRequest("park", null, List.of()));
            assertEquals(scenario.equals("unsupported_plan") ? "TOOL_FAILED" : "TOOL_LIMIT", result.termination().name());
            verify(llm, times(scenario.equals("repeated") ? 2 : 1)).chat(anyList(), anyList());
            verify(searches, times(scenario.equals("repeated") ? 1 : 0)).search(any(PlaceSearchRequest.class));
        }
    }

    @Test
    void toolNeedsOnlyQueryAndPreservesOriginalsRelationsAndSupplementSeparation() throws Exception {
        var searches = mock(PlaceSemanticSearchService.class);
        var place = mapper.readValue("{\"id\":101,\"name\":\"A\",\"description\":\"summary\"}", PlaceResult.class);
        when(searches.search(any(PlaceSearchRequest.class))).thenReturn(List.of(new PlaceSemanticSearchResult(place, .8f, List.of(
                new SearchEvidenceChunk(chunk(mapper, ORIGINAL, WALK)), new SearchEvidenceChunk(chunk(mapper, BLOCK, BLOCK))))));
        var tool = new SearchPlacesTool(searches, resolver, new ContextPlanPromptFactory(mapper), mapper);
        var result = tool.execute(ConversationTool.Invocation.builder().request(new ConversationRequest("야경", null, List.of()))
                .arguments(mapper.readTree("{\"query\":\"야경\"}")).build());
        assertEquals("place-search-v2", result.modelData().path("searchContractVersion").asText());
        assertFalse(result.modelData().has("request"));
        JsonNode evidence = result.modelData().path("candidates").get(0).path("selectedEvidence");
        assertEquals(ORIGINAL, evidence.get(0).path("original").path("chunk_text").asText());
        assertEquals(BLOCK, evidence.get(1).path("original").path("chunk_text").asText());
        assertEquals(SUPPLEMENT, evidence.get(0).path("generatedSupplement").path("context_text").asText());
        assertEquals(chunk(mapper, ORIGINAL, WALK).path("relations"), evidence.get(0).path("annotations").path("relations"));
        assertEquals(Set.copyOf(result.sources().keySet()),
                java.util.stream.StreamSupport.stream(evidence.spliterator(), false).map(row -> row.path("evidenceId").asText()).collect(Collectors.toSet()));
        verify(searches).search(argThat(criteria -> criteria.query().equals("야경") && criteria.limit() == 10 && criteria.area() == null));
    }

    @Test
    void structuredContextInheritsAndUnionsExclusionsButRejectsConflictingScope() throws Exception {
        var context = new PlaceSearchContext("서울", "종로", null, List.of(378L), null);
        var request = new ConversationRequest("질문", null, List.of(), context);
        var resolved = resolver.resolve(request, mapper.readTree("{\"query\":\"궁궐\",\"region\":null,\"exclude_place_ids\":[378,379]}"));
        assertEquals("서울", resolved.criteria().region());
        assertEquals(List.of(378L, 379L), resolved.criteria().excludePlaceIds());
        assertEquals(PlaceSearchCriteriaResolver.Origin.UNION, resolved.provenance().get("excludePlaceIds"));
        assertTrue(assertThrows(IllegalArgumentException.class,
                () -> resolver.resolve(request, mapper.readTree("{\"query\":\"궁궐\",\"region\":\"부산\"}")))
                .getMessage().contains("SEARCH_SCOPE_CONFLICT"));
    }

    @Test
    void realServiceAndKafkaBuilderReceiveEveryFilterWithoutPlanningInput() throws Exception {
        var request = mapper.readValue("""
                {"query":"가족 공원","region":"서울","city":"종로","excludePlaceIds":[378],
                 "area":{"type":"CIRCLE","center":{"lat":37.57,"lon":126.98},"radiusMeters":500}}
                """, PlaceSearchRequest.class);
        var client = mock(PlaceSemanticSearchClient.class);
        var service = new PlaceSemanticSearchService(client);
        service.search(request);
        verify(client).search(eq(request.query()), eq("서울"), eq("종로"), isNull(), eq(10),
                eq(request.area().toPlanArea()), eq(RankingMode.RERANKED), eq(List.of(378L)));
        var actual = new PlaceSemanticSearchClient(mock(JdbcTemplate.class), mapper, mock(TransactionTemplate.class),
                mock(SearchTracing.class), "mock-topic", 1);
        JsonNode kafka = ReflectionTestUtils.invokeMethod(actual, "buildRequest", UUID.randomUUID(), request.query(),
                request.region(), request.city(), "공원", request.limit(), request.area().toPlanArea(), request.rankingMode(), request.excludePlaceIds());
        assertEquals("서울", kafka.path("filters").path("region").asText());
        assertEquals("종로", kafka.path("filters").path("city").asText());
        assertEquals("공원", kafka.path("filters").path("category").asText());
        assertEquals(378, kafka.path("filters").path("exclude_place_ids").get(0).asInt());
        assertEquals(500, kafka.path("filters").path("area").path("radius_meters").asInt());
        assertEquals(37.57, kafka.path("filters").path("area").path("center").path("lat").asDouble());
        assertEquals("RERANKED", kafka.path("ranking_mode").asText());
    }

    @Test
    void postSearchValidatesBeforeServiceAndRetainsDefaultGetContract() throws Exception {
        var service = mock(PlaceSemanticSearchService.class);
        var mvc = MockMvcBuilders.standaloneSetup(new PlaceSearchController(service)).build();
        mvc.perform(post("/api/places/search").contentType("application/json").content("{\"query\":\"궁궐\"}"))
                .andExpect(status().isOk());
        verify(service).search(argThat(criteria -> criteria.limit() == 10 && criteria.rankingMode() == RankingMode.RERANKED));
        clearInvocations(service);
        mvc.perform(post("/api/places/search").contentType("application/json").content("{\"query\":\"park\",\"planningRequest\":{}}"))
                .andExpect(status().isBadRequest());
        mvc.perform(post("/api/places/search").contentType("application/json").content("{\"query\":\"park\",\"region\":\" \"}"))
                .andExpect(status().isBadRequest());
        mvc.perform(post("/api/places/search").contentType("application/json").content("""
                {"query":"궁궐","area":{"type":"CIRCLE","center":{"lat":100,"lon":126},"radiusMeters":499}}
                """ )).andExpect(status().isBadRequest());
        verifyNoInteractions(service);
    }

    @Test
    void allEightyFiveExistingFilterProjectionsPassThroughTheRuntimeServiceWithoutAPlan() throws Exception {
        var client = mock(PlaceSemanticSearchClient.class);
        var service = new PlaceSemanticSearchService(client);
        int count = 0;
        for (String line : Files.readAllLines(Path.of("../../Evaluation/runs/contextual/exact-qwen-and-search-contract-v1/20261102-01/search-case-mapping.jsonl"))) {
            var request = mapper.treeToValue(mapper.readTree(line).path("proposed_search_request"), PlaceSearchRequest.class);
            service.search(request);
            verify(client).search(eq(request.query()), eq(request.region()), eq(request.city()), eq(request.category()), eq(request.limit()),
                    eq(request.area() == null ? null : request.area().toPlanArea()), eq(request.rankingMode()), eq(request.excludePlaceIds()));
            clearInvocations(client);
            count++;
        }
        assertEquals(85, count);
    }

    @Test
    void legacyPlanAreaIsExplicitAndInvalidFiltersCannotReachKafka() throws Exception {
        var plan = mapper.readValue(PlanContextContractTest.REQUEST, GeneratePlanRequest.class);
        var result = resolver.resolve(new ConversationRequest("질문", plan, List.of()), mapper.readTree("{\"query\":\"야경\"}"));
        assertEquals(plan.context().area(), result.criteria().area().toPlanArea());
        assertEquals(PlaceSearchCriteriaResolver.Origin.LEGACY_PLAN_AREA, result.provenance().get("area"));
        var client = mock(PlaceSemanticSearchClient.class);
        var service = new PlaceSemanticSearchService(client);
        assertThrows(IllegalArgumentException.class, () -> service.search(new PlaceSearchRequest("x", null, null, null,
                List.of(-1L), null, 10, RankingMode.RERANKED)));
        assertThrows(IllegalArgumentException.class, () -> resolver.resolve(new ConversationRequest("질문", null, List.of()),
                mapper.readTree("{\"query\":\"x\",\"exclude_place_ids\":[1.5]}")));
        verifyNoInteractions(client);
    }
}
