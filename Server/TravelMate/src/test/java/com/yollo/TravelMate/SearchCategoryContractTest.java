package com.yollo.TravelMate;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.stream.StreamSupport;
import java.security.MessageDigest;
import java.util.HexFormat;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.ai.llm.base.*;
import com.yollo.TravelMate.ai.llm.derived.OpenAiToolContracts;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.conversation.data.*;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.*;
import com.yollo.TravelMate.domain.place.client.PlaceSemanticSearchClient;
import com.yollo.TravelMate.domain.place.data.request.*;
import com.yollo.TravelMate.domain.place.enums.PlaceSearchCategories;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.NullSource;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class SearchCategoryContractTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final PlaceSearchCriteriaResolver resolver = new PlaceSearchCriteriaResolver();

    private JsonNode recordedResponse() throws Exception {
        try (InputStream input = getClass().getResourceAsStream("/search-category/openai-palaces-03.response.json")) {
            assertNotNull(input);
            return mapper.readTree(input);
        }
    }

    private LlmTurn.ToolCall recordedCall() throws Exception {
        var output = recordedResponse().path("output").get(0);
        return new LlmTurn.ToolCall(
                output.path("call_id").asText(),
                output.path("name").asText(),
                output.path("arguments").asText()
        );
    }

    private OpenAiToolContracts.PreparedTool strictTool() {
        return OpenAiToolContracts.prepare(
                List.of(new SearchPlacesTool(null, null, null, mapper).definition()),
                OpenAiToolContracts.Mode.STRICT_SEARCH_V1
        ).get(0);
    }

    @Test
    void recordedProviderResponseRetainsItsOriginalHash() throws Exception {
        try (InputStream original = getClass().getResourceAsStream("/search-category/openai-palaces-03.response.json");
             InputStream provenance = getClass().getResourceAsStream("/search-category/provenance.json")) {
            assertNotNull(original);
            assertNotNull(provenance);
            String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(original.readAllBytes()));
            assertEquals(mapper.readTree(provenance).path("provider_response_sha256").asText(), hash);
        }
    }

    @Test
    void providerAndServerPublishTheLabelsThatIndexingStores() {
        var labels = Arrays.stream(TourContentType.values()).map(TourContentType::getLabel).toList();
        assertEquals(labels, PlaceSearchCategories.allowedValues());
        var canonical = SearchPlacesContract.parameters().path("properties").path("category");
        var strict = strictTool().parameters().path("properties").path("category");
        assertEquals(canonical, strict);
        assertEquals(labels, StreamSupport.stream(canonical.path("anyOf").get(0).path("enum").spliterator(), false)
                .map(JsonNode::asText).toList());
        assertEquals("null", canonical.path("anyOf").get(1).path("type").asText());
    }

    @ParameterizedTest
    @EnumSource(TourContentType.class)
    void everyStoredCategoryPassesThroughBothServiceEntrypointsWithoutChangingQuery(TourContentType contentType) throws Exception {
        ObjectNode arguments = mapper.readTree(recordedCall().arguments()).deepCopy();
        arguments.put("category", contentType.getLabel());
        ToolSchemas.validate(strictTool().parameters(), arguments);
        var criteria = resolver.resolve(new ConversationRequest("original", null, List.of()), arguments).criteria();
        assertEquals(arguments.path("query").asText(), criteria.query());
        assertEquals(contentType.getLabel(), criteria.category());
        var client = mock(PlaceSemanticSearchClient.class);
        var service = new PlaceSemanticSearchService(client);
        service.search(criteria);
        verify(client).search(
                eq(criteria.query()),
                eq(criteria.region()),
                eq(criteria.city()),
                eq(contentType.getLabel()),
                eq(criteria.limit()),
                isNull(),
                eq(criteria.rankingMode()),
                eq(criteria.excludePlaceIds())
        );
        service.search(criteria.query(), criteria.region(), criteria.city(), contentType.getLabel(), criteria.limit());
        verify(client).search(
                eq(criteria.query()),
                eq(criteria.region()),
                eq(criteria.city()),
                eq(contentType.getLabel()),
                eq(criteria.limit()),
                isNull(),
                eq(criteria.rankingMode())
        );
    }

    @ParameterizedTest
    @ValueSource(strings = {"궁", "조용한", "왕실 가족의 거처", "관광지 ", "MUSEUM", ""})
    void unknownCategoriesAreRejectedBySchemasAndServerBeforeSearch(String category) throws Exception {
        ObjectNode arguments = mapper.readTree(recordedCall().arguments()).deepCopy();
        arguments.put("category", category);
        String original = arguments.toString();
        assertThrows(IllegalArgumentException.class, () -> SearchPlacesContract.validate(arguments));
        assertThrows(IllegalArgumentException.class, () -> ToolSchemas.validate(strictTool().parameters(), arguments));
        assertThrows(IllegalArgumentException.class, () -> resolver.resolve(new ConversationRequest("original", null, List.of()), arguments));
        var criteria = new PlaceSearchRequest(
                arguments.path("query").asText(),
                null,
                null,
                category,
                List.of(),
                null,
                10,
                PlaceSemanticSearchService.RankingMode.RERANKED
        );
        var client = mock(PlaceSemanticSearchClient.class);
        var service = new PlaceSemanticSearchService(client);
        assertThrows(IllegalArgumentException.class, () -> service.search(criteria));
        assertThrows(IllegalArgumentException.class, () -> service.search(criteria.query(), null, null, category, 10));
        verifyNoInteractions(client);
        assertEquals(original, arguments.toString());
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(strings = {"관광지"})
    void detailedTraitsStayInQueryAndOptionalCategoryIsNotInferred(String category) throws Exception {
        String query = "조용한 궁에서 왕실 가족의 거처를 둘러보고 싶어";
        var arguments = mapper.createObjectNode().put("query", query);
        if (category != null) arguments.put("category", category);
        var request = new ConversationRequest("original", null, List.of());
        var omitted = resolver.resolve(request, arguments).criteria();
        assertEquals(query, omitted.query());
        assertEquals(category, omitted.category());
        if (category == null) {
            arguments.putNull("category");
            assertEquals(omitted, resolver.resolve(request, arguments).criteria());
        }
    }

    @Test
    void invalidInheritedCategoryCannotReachSearch() {
        var context = new PlaceSearchContext(null, null, "궁", List.of(), null);
        var request = new ConversationRequest("original", null, List.of(), context);
        var arguments = mapper.createObjectNode().put("query", "왕실 가족의 거처");
        assertThrows(IllegalArgumentException.class, () -> resolver.resolve(request, arguments));
        arguments.putNull("category");
        assertThrows(IllegalArgumentException.class, () -> resolver.resolve(request, arguments));
        assertEquals("궁", context.category());
    }

    @Test
    void recordedStrictArgumentsAreRejectedWithOriginalReceiptAndNoCorrection() throws Exception {
        var original = recordedCall();
        List<JsonNode> events = new ArrayList<>();
        var context = ObservationContext.Context.builder()
                .mode(ObservationContext.Mode.MOCK)
                .phase(ObservationContext.Phase.CONVERSATION)
                .sink(events::add)
                .build();
        try (var ignored = ObservationContext.open(context)) {
            assertThrows(IllegalArgumentException.class, () -> strictTool().adapt(original));
        }
        var receipt = events.get(0).path("payload");
        assertEquals("REJECTED", receipt.path("status").asText());
        assertEquals(original.arguments(), receipt.path("originalArguments").asText());
        assertTrue(receipt.path("serverArguments").isNull());
    }

    @Test
    void recordedCategoryFailureStopsCanonicalToolExecutionWithoutSearchOrRetry() throws Exception {
        var call = recordedCall();
        var searches = mock(PlaceSemanticSearchService.class);
        var tool = new SearchPlacesTool(searches, resolver, new ContextPlanPromptFactory(mapper), mapper);
        var registry = new ConversationToolRegistry(List.of(tool), "SEARCH_PLACES");
        var llm = mock(LlmClient.class);
        when(llm.chat(anyList(), anyList())).thenReturn(LlmTurn.builder().toolCalls(List.of(call)).build());
        var service = new ConversationService(
                llm,
                registry,
                new ConversationToolExecutor(registry, mapper),
                new ConversationAnswerRenderer(mapper),
                mapper,
                2,
                1,
                ConversationService.ToolFailurePolicy.STOP
        );
        var response = service.respond("offline-owner", UUID.randomUUID(), new ConversationRequest("original", null, List.of()));
        assertEquals(ConversationResponse.Termination.TOOL_FAILED, response.termination());
        assertEquals(ConversationResponse.ToolStatus.FAILED, response.toolResults().get(0).status());
        assertEquals(call.arguments(), response.toolResults().get(0).arguments());
        verifyNoInteractions(searches);
        verify(llm, times(1)).chat(anyList(), anyList());
    }
}
