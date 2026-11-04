package com.yollo.TravelMate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.base.LlmMessage;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.budget.TokenBudgetException;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.pipeline.*;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationModuleConfig.SearchRanking;
import com.yollo.TravelMate.domain.conversation.tool.PlaceSearchCriteriaResolver;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService.RankingMode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.springframework.beans.BeansException;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.io.DefaultResourceLoader;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ConversationModulesTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final ConversationModuleConfig defaults = ConversationModuleConfig.defaults();
    @TempDir
    Path temporary;

    private ConversationModuleConfig configured(SearchRanking ranking, String resource) {
        return new ConversationModuleConfig(
                defaults.search(), defaults.evidence(), defaults.prompt(), defaults.model(), ranking, resource
        );
    }

    private PlaceSearchCriteriaResolver.Resolved input(RankingMode ranking) {
        return new PlaceSearchCriteriaResolver.Resolved(
                new PlaceSearchRequest("종로의 왕실 가족 거처", "서울", "종로", "관광지", List.of(17L), null, 5, ranking),
                Map.of("region", PlaceSearchCriteriaResolver.Origin.SEARCH_CONTEXT)
        );
    }

    @ParameterizedTest
    @EnumSource(SearchRanking.class)
    void searchRankingIsConfigurationWithoutCopyingRetrievalOrChangingOtherFilters(SearchRanking ranking) {
        var service = mock(PlaceSemanticSearchService.class);
        when(service.search(any(PlaceSearchRequest.class))).thenReturn(List.of());
        var original = input(RankingMode.RERANKED);
        var config = configured(ranking, defaults.promptResource());
        var batch = new KafkaSearchV1(service).execute(original, config);
        assertEquals(ranking.resolve(original.criteria().rankingMode()), batch.resolved().criteria().rankingMode());
        assertEquals(original.criteria().query(), batch.resolved().criteria().query());
        assertEquals(original.criteria().region(), batch.resolved().criteria().region());
        assertEquals(original.criteria().city(), batch.resolved().criteria().city());
        assertEquals(original.criteria().category(), batch.resolved().criteria().category());
        assertEquals(original.criteria().excludePlaceIds(), batch.resolved().criteria().excludePlaceIds());
        assertEquals(original.criteria().limit(), batch.resolved().criteria().limit());
        assertEquals(original.provenance(), batch.resolved().provenance());
        verify(service).search(batch.resolved().criteria());
        verifyNoMoreInteractions(service);
    }

    @Test
    void requestDefaultAlsoPreservesExplicitSemanticOnlyRequest() {
        var service = mock(PlaceSemanticSearchService.class);
        when(service.search(any(PlaceSearchRequest.class))).thenReturn(List.of());
        var original = input(RankingMode.SEMANTIC_ONLY);
        var result = new KafkaSearchV1(service).execute(original, defaults);
        assertEquals(original, result.resolved());
    }

    @Test
    void replacingSearchOrEvidenceLeavesOneSharedExecutionOrder() {
        var search = mock(SearchModule.class);
        var evidence = mock(EvidenceModule.class);
        when(search.supports(defaults.search())).thenReturn(true);
        when(evidence.supports(defaults.evidence())).thenReturn(true);
        var original = input(RankingMode.RERANKED);
        var batch = new SearchModule.Batch(original, List.of());
        when(search.execute(original, defaults)).thenReturn(batch);
        var expected = com.yollo.TravelMate.domain.conversation.tool.ConversationTool.Result.builder().build();
        when(evidence.execute(batch, defaults)).thenReturn(expected);
        var pipeline = new ConversationSearchPipeline(List.of(search), List.of(evidence), defaults);
        assertSame(expected, pipeline.execute(original));
        var ordered = inOrder(search, evidence);
        ordered.verify(search).execute(original, defaults);
        ordered.verify(evidence).execute(batch, defaults);
    }

    @Test
    void searchFailureDoesNotBuildEvidenceOrTryAnAlternateModule() {
        var search = mock(SearchModule.class);
        var evidence = mock(EvidenceModule.class);
        when(search.supports(defaults.search())).thenReturn(true);
        when(evidence.supports(defaults.evidence())).thenReturn(true);
        var original = input(RankingMode.RERANKED);
        when(search.execute(original, defaults)).thenThrow(new IllegalStateException("saved search failure"));
        var pipeline = new ConversationSearchPipeline(List.of(search), List.of(evidence), defaults);
        assertThrows(IllegalStateException.class, () -> pipeline.execute(original));
        verify(evidence, never()).execute(any(), any());
        verify(search).execute(original, defaults);
    }

    @Test
    void absentAndAmbiguousComponentsFailAtConstruction() {
        var search = mock(SearchModule.class);
        var evidence = mock(EvidenceModule.class);
        when(search.supports(defaults.search())).thenReturn(true);
        when(evidence.supports(defaults.evidence())).thenReturn(true);
        assertThrows(IllegalStateException.class, () -> new ConversationSearchPipeline(List.of(), List.of(evidence), defaults));
        assertThrows(IllegalStateException.class, () -> new ConversationSearchPipeline(List.of(search, search), List.of(evidence), defaults));
        assertThrows(IllegalStateException.class, () -> new ConversationSearchPipeline(List.of(search), List.of(), defaults));
        assertThrows(IllegalStateException.class, () -> new ConversationSearchPipeline(List.of(search), List.of(evidence, evidence), defaults));
        verify(search, never()).execute(any(), any());
    }

    @Test
    void defaultPromptMatchesThePreviousJavaTextBlockExactly() {
        var prompt = new ResourcePromptV1(defaults, new DefaultResourceLoader());
        assertEquals("981cd883794d751f63b0fca1c0bc29734d9ae19b4c844634c695368a1b9b81d2", prompt.sha256());
        assertTrue(prompt.execute(null, defaults).contains("serverEvidence"));
    }

    @Test
    void promptContentIsSettingsAndIsLoadedOncePerServerInstance() throws Exception {
        var resource = temporary.resolve("v2-prompt.txt");
        Files.writeString(resource, "별도 평가 프롬프트 A\n");
        var config = configured(SearchRanking.REQUEST_DEFAULT, resource.toUri().toString());
        var prompt = new ResourcePromptV1(config, new DefaultResourceLoader());
        var fingerprint = prompt.sha256();
        Files.writeString(resource, "다음 실행의 프롬프트 B\n");
        assertEquals("별도 평가 프롬프트 A\n", prompt.execute(null, config));
        assertEquals(fingerprint, prompt.sha256());
        assertNotEquals(new ResourcePromptV1(config, new DefaultResourceLoader()).sha256(), fingerprint);
    }

    @Test
    void missingEmptyOrRemotePromptCannotTriggerAModelCall() throws Exception {
        var missing = configured(SearchRanking.REQUEST_DEFAULT, temporary.resolve("missing.txt").toUri().toString());
        assertThrows(IllegalStateException.class, () -> new ResourcePromptV1(missing, new DefaultResourceLoader()));
        var blank = temporary.resolve("blank.txt");
        Files.writeString(blank, "  \n");
        var empty = configured(SearchRanking.REQUEST_DEFAULT, blank.toUri().toString());
        assertThrows(IllegalArgumentException.class, () -> new ResourcePromptV1(empty, new DefaultResourceLoader()));
        assertThrows(IllegalArgumentException.class, () -> configured(SearchRanking.REQUEST_DEFAULT, "https://invalid.example/prompt.txt"));
    }

    @Test
    void modelReplacementUsesTheSameInputAndOneExecuteCall() {
        var prompt = mock(PromptModule.class);
        var model = mock(ModelModule.class);
        when(prompt.supports(defaults.prompt())).thenReturn(true);
        when(model.supports(defaults.model())).thenReturn(true);
        var request = new ConversationRequest("질문", null, List.of());
        when(prompt.execute(request, defaults)).thenReturn("선택한 프롬프트");
        var pipeline = new ConversationGenerationPipeline(List.of(prompt), List.of(model), defaults);
        var input = new ModelModule.Input(List.of(LlmMessage.text(LlmMessage.Role.USER, request.message())), List.of());
        var completion = LlmTurn.builder().content("합성 응답").build();
        when(model.execute(input, defaults)).thenReturn(completion);
        assertEquals("선택한 프롬프트", pipeline.systemPrompt(request));
        assertSame(completion, pipeline.execute(input));
        verify(model).execute(input, defaults);
    }

    @Test
    void modelGuardFailureIsNotSwallowedRetriedOrRoutedToAnotherProvider() {
        var client = mock(LlmClient.class);
        var input = new ModelModule.Input(List.of(), List.of());
        var blocked = new TokenBudgetException(TokenBudgetException.Reason.COUNT_UNAVAILABLE);
        when(client.chat(input.messages(), input.tools())).thenThrow(blocked);
        assertSame(blocked, assertThrows(TokenBudgetException.class, () -> new GuardedModelV1(client).execute(input, defaults)));
        verify(client).chat(input.messages(), input.tools());
        verifyNoMoreInteractions(client);
    }

    @Test
    void modelInputSnapshotsTheCompleteMessagesAndDefinitions() {
        var messages = new ArrayList<LlmMessage>();
        messages.add(LlmMessage.text(LlmMessage.Role.USER, "자르지 않은 원문"));
        var input = new ModelModule.Input(messages, List.of());
        messages.clear();
        assertEquals("자르지 않은 원문", input.messages().get(0).content());
        assertThrows(UnsupportedOperationException.class, () -> input.messages().clear());
    }

    @Test
    void invalidConfiguredVersionFailsSpringWiringBeforeAnyRequest() {
        try (var context = new AnnotationConfigApplicationContext()) {
            context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("invalid-module", Map.of(
                    "travelmate.conversation.modules.search", "UNKNOWN_V99"
            )));
            context.register(ConversationModuleConfig.class);
            assertThrows(BeansException.class, context::refresh);
        }
    }
}
