package com.yollo.TravelMate;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.base.LlmMessage;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.base.StructuredOutput;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationIntent;
import com.yollo.TravelMate.domain.conversation.data.DisplayedResult;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchContext;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.data.RecommendationJobResponse;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationGenerationPipeline;
import com.yollo.TravelMate.domain.conversation.repository.RecommendationJobRepository;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import com.yollo.TravelMate.domain.place.data.internal.Sido;
import com.yollo.TravelMate.domain.place.data.result.PlaceCoverage;
import com.yollo.TravelMate.domain.place.service.PlaceCoverageService;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class RecommendationJobServiceTest {
    private static final String QUERY = "종로 조선 왕실 궁궐";
    private final ObjectMapper mapper = new ObjectMapper();
    private final RecommendationJobRepository jobs = mock(RecommendationJobRepository.class);
    private final LlmClient llm = mock(LlmClient.class);
    private final AtomicReference<String> searched = new AtomicReference<>();
    private final PlaceCoverageService coverage = mock(PlaceCoverageService.class);

    @BeforeEach
    void coverageUnknownUnlessATestSetsIt() {
        when(coverage.current()).thenReturn(PlaceCoverage.UNKNOWN);
    }

    @Test
    void searchesWithLilisQueryAndStoresHerCutsWithTheCards() throws Exception {
        var stored = run("""
                {"intent":"RECOMMENDATION","answerKind":"PLACE_GUIDANCE","citations":[],
                 "dialogue":[{"text":"조건에 딱 맞는 곳은 못 찾았어.","emotion":"SAD"},
                             {"text":"범위를 조금 넓혀서 다시 찾아볼까?","emotion":"THINKING"}]}""");
        assertEquals(QUERY, searched.get(), "retrieval uses LiLi's query, not the raw sentence");
        assertEquals("PLACES", stored.path("type").asText());
        assertEquals("LLM", stored.path("messageSource").asText());
        assertEquals(2, stored.path("dialogue").size());
        assertEquals("조건에 딱 맞는 곳은 못 찾았어.", stored.path("message").asText());
        assertEquals("SAD", stored.path("emotion").asText());
    }

    @Test
    void aCitationOutsideTheDeliveredEvidenceKeepsTheCardsButNotTheLines() throws Exception {
        var stored = run("""
                {"intent":"RECOMMENDATION","answerKind":"PLACE_GUIDANCE",
                 "citations":[{"placeId":378,"evidenceId":"invented","sourceId":"invented","quote":"지어낸 문장"}],
                 "dialogue":[{"text":"찾았어!","emotion":"EXCITED"},{"text":"여기 정말 좋아.","emotion":"HAPPY"}]}""");
        assertEquals("PLACES", stored.path("type").asText());
        assertEquals("SERVER_FALLBACK", stored.path("messageSource").asText());
        assertEquals("INVALID_RESPONSE", stored.path("termination").asText());
    }

    // Live runs had LiLi describe or cite a card she had no original for; she must not receive it at all.
    @Test
    void aCandidateWithoutSelectedEvidenceReachesLiliOnlyAsACount() throws Exception {
        var modelData = mapper.readTree("""
                {"searchContractVersion":"place-search-v2","candidates":[
                  {"placeId":378,"name":"창경궁","description":"관광지. 고궁. 카드 요약",
                   "selectedEvidence":[{"evidenceId":"E378-0","original":{"chunk_text":"주로 왕실 가족들의 생활공간으로 사용하였다.",
                     "source_id":"f9778e87-11f5-5d07-83fa-33e8350a3a40",
                     "source_version":"584360f560922c2194641c1b365a263851cc0edf0a1170cc0d3c4da955cab3fe",
                     "metadata":{"field":"places.description",
                                 "corpus_sha256":"c74e902620687cbe8b7ec61a24eb7932e95f8cf7a90762baef5e78ad0b134f9e"}}}],
                   "evidenceAvailability":"SELECTED_UNASSESSED"},
                  {"placeId":380,"name":"창덕궁 낙선재","description":"대한제국 마지막 황실 가족이 생활하다가 세상을 떠난 곳",
                   "selectedEvidence":[],"evidenceAvailability":"NONE_SELECTED"}]}""");
        run("""
                {"intent":"RECOMMENDATION","answerKind":"PLACE_GUIDANCE","citations":[],
                 "dialogue":[{"text":"카드에서 골라 줘.","emotion":"GUIDING"},{"text":"더 알아봐 줄게.","emotion":"HAPPY"}]}""",
                modelData);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<LlmMessage>> messages = ArgumentCaptor.forClass((Class<List<LlmMessage>>) (Class<?>) List.class);
        verify(llm).chat(messages.capture(), anyList(), any(StructuredOutput.class));
        String sent = messages.getValue().stream().map(LlmMessage::content).collect(Collectors.joining("\n"));
        assertTrue(sent.contains("창경궁"), "the citable candidate stays");
        assertFalse(sent.contains("낙선재"), "an uncitable candidate's name is not sent");
        assertFalse(sent.contains("대한제국 마지막 황실"), "nor its description");
        assertTrue(sent.contains("\"cardOnlyCandidateCount\":1"));
        assertTrue(sent.contains("\"shownCardCount\":2"), "she knows the cards are on screen even when she can cite none");
        // Tokens she cannot use: provenance hashes and a card summary that repeats the original she cites.
        assertFalse(sent.contains("c74e902620687cbe"), "hashes are left in the event, not sent to the model");
        assertFalse(sent.contains("584360f560922c21"));
        assertFalse(sent.contains("카드 요약"));
        assertTrue(sent.contains("f9778e87-11f5-5d07-83fa-33e8350a3a40"), "the source id that citations need stays");
        assertTrue(sent.contains("places.description"), "short metadata that is not a hash stays");
    }

    // Live runs: after a search LiLi suggested switching to Busan, which the place data does not hold.
    @Test
    void theExplanationKnowsWhichAreasAndKindsThePlaceDataHolds() throws Exception {
        when(coverage.current()).thenReturn(new PlaceCoverage(List.of(Sido.SEOUL), List.of("관광지")));
        run("""
                {"intent":"RECOMMENDATION","answerKind":"PLACE_GUIDANCE","citations":[],
                 "dialogue":[{"text":"카드에서 골라 줘.","emotion":"GUIDING"},{"text":"더 알아봐 줄게.","emotion":"HAPPY"}]}""");
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<LlmMessage>> messages = ArgumentCaptor.forClass((Class<List<LlmMessage>>) (Class<?>) List.class);
        verify(llm).chat(messages.capture(), anyList(), any(StructuredOutput.class));
        String sent = messages.getValue().stream().map(LlmMessage::content).collect(Collectors.joining("\n"));
        assertTrue(sent.contains("\"searchCoverage\":{\"regions\":[\"서울\"],\"categories\":[\"관광지\"]}"));
    }

    private com.fasterxml.jackson.databind.JsonNode run(String recommendation) throws Exception {
        return run(recommendation, mapper.createObjectNode().set("candidates", mapper.createArrayNode()));
    }

    private com.fasterxml.jackson.databind.JsonNode run(
            String recommendation,
            com.fasterxml.jackson.databind.JsonNode modelData
    ) throws Exception {
        return run(recommendation, modelData, mapper.createArrayNode(),
                new ConversationRequest("왕실 가족이 살던 궁 찾아줘", null, List.of()));
    }

    @Test
    void realCardRegionsAndCompletedExactExclusionsReachTheFinalModelWithoutUncitableDescriptions() throws Exception {
        // c1 regression: all cards lack originals; the old prompt hid their regions and the completed exclusion.
        var cards = mapper.readTree("""
                [{"placeId":188,"name":"서순라길","region":"서울","city":"종로"},
                 {"placeId":272,"name":"안양암","region":"서울","city":"종로"}]
                """);
        var modelData = mapper.readTree("""
                {"searchCriteria":{"region":"서울","excludePlaceIds":[173,368]},"candidates":[
                 {"placeId":188,"name":"서순라길","description":"인용 불가 설명","selectedEvidence":[]},
                 {"placeId":272,"name":"안양암","selectedEvidence":[]}]}
                """);
        var request = new ConversationRequest("부산 해운대에서 찾아줘. 세 번째도 빼 줘.", null, List.of(),
                new PlaceSearchContext("서울", null, null, List.of(173L, 368L), null), ConversationIntent.AUTO,
                new DisplayedResult(UUID.randomUUID(), List.of(188L, 272L, 368L)));
        var stored = run("""
                {"intent":"RECOMMENDATION","answerKind":"PLACE_GUIDANCE","citations":[],"dialogue":[
                 {"text":"세 번째 장소를 빼고 찾았어. 지금 카드는 서울 지역이야.","emotion":"GUIDING"},
                 {"text":"부산을 찾으려면 앱의 검색 범위를 바꿔 줘.","emotion":"THINKING"}]}
                """, modelData, cards, request);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<LlmMessage>> messages = ArgumentCaptor.forClass((Class<List<LlmMessage>>) (Class<?>) List.class);
        verify(llm).chat(messages.capture(), anyList(), any(StructuredOutput.class));
        String sent = messages.getValue().stream().map(LlmMessage::content).collect(Collectors.joining("\n"));
        assertTrue(sent.contains("\"returnedLocations\":[{\"region\":\"서울\",\"city\":\"종로\"}]"));
        assertTrue(sent.contains("\"exclusionStatus\":\"VERIFIED\""));
        assertTrue(sent.contains("\"excludedDisplayedPositions\":[3]"));
        assertFalse(sent.contains("인용 불가 설명"));
        assertEquals(cards, stored.path("data"), "execution facts do not rewrite the actual search result");
    }

    private com.fasterxml.jackson.databind.JsonNode run(
            String recommendation,
            com.fasterxml.jackson.databind.JsonNode modelData,
            com.fasterxml.jackson.databind.JsonNode cards,
            ConversationRequest request
    ) throws Exception {
        when(jobs.insert(any(), anyString(), any(), anyString())).thenReturn(true);
        when(jobs.get(any(), anyString())).thenAnswer(invocation -> Optional.of(new RecommendationJobResponse(
                invocation.getArgument(0), JobStatus.QUEUED, "status", null, null)));
        when(llm.chat(anyList(), anyList(), any(StructuredOutput.class)))
                .thenReturn(LlmTurn.builder().content(recommendation).build());
        var evidence = new ConversationEvidencePreparation(List.of(new ConversationEvidenceStrategy() {
            @Override
            public boolean supports(ConversationToolRegistry registry) {
                return true;
            }

            @Override
            public ConversationTool.Result prepare(String userUid, UUID turnKey, ConversationRequest request,
                                                   ConversationToolRegistry registry) {
                searched.set(request.message());
                return ConversationTool.Result.builder().type(ResultType.PLACES).publicData(cards)
                        .modelData(modelData).build();
            }

            @Override
            public ConversationTool.Name source() {
                return ConversationTool.Name.SEARCH_PLACES;
            }
        }));
        var service = new RecommendationJobService(jobs, evidence, new ConversationToolRegistry(List.of()),
                new LiliTurns(ConversationGenerationPipeline.defaults(llm), mapper), new ConversationAnswerRenderer(mapper), mapper,
                coverage);
        var queued = service.submit("owner", UUID.randomUUID(), request, QUERY);
        assertEquals(ResultType.RECOMMENDATION_JOB, queued.type());
        var result = ArgumentCaptor.forClass(String.class);
        verify(jobs, timeout(5000)).update(any(), eq(JobStatus.SUCCEEDED), result.capture(), isNull());
        verify(llm).chat(anyList(), eq(List.of()), argThat(output -> output.name().equals(LiliTurnContract.RECOMMENDATION_NAME)));
        return mapper.readTree(result.getValue());
    }
}
