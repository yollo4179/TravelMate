package com.yollo.TravelMate;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.base.StructuredOutput;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.data.RecommendationJobResponse;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationGenerationPipeline;
import com.yollo.TravelMate.domain.conversation.repository.RecommendationJobRepository;
import com.yollo.TravelMate.domain.conversation.service.*;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;
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

    private com.fasterxml.jackson.databind.JsonNode run(String recommendation) throws Exception {
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
                var empty = mapper.createArrayNode();
                return ConversationTool.Result.builder().type(ResultType.PLACES).publicData(empty)
                        .modelData(mapper.createObjectNode().set("candidates", mapper.createArrayNode())).build();
            }

            @Override
            public ConversationTool.Name source() {
                return ConversationTool.Name.SEARCH_PLACES;
            }
        }));
        var service = new RecommendationJobService(jobs, evidence, new ConversationToolRegistry(List.of()),
                new LiliTurns(ConversationGenerationPipeline.defaults(llm), mapper), new ConversationAnswerRenderer(mapper), mapper);
        var queued = service.submit("owner", UUID.randomUUID(), new ConversationRequest("왕실 가족이 살던 궁 찾아줘", null, List.of()), QUERY);
        assertEquals(ResultType.RECOMMENDATION_JOB, queued.type());
        var result = ArgumentCaptor.forClass(String.class);
        verify(jobs, timeout(5000)).update(any(), eq(JobStatus.SUCCEEDED), result.capture(), isNull());
        verify(llm).chat(anyList(), eq(List.of()), argThat(output -> output.name().equals(LiliTurnContract.RECOMMENDATION_NAME)));
        return mapper.readTree(result.getValue());
    }
}
