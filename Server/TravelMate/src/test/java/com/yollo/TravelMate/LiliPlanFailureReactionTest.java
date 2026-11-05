package com.yollo.TravelMate;

import java.util.List;
import java.util.stream.Collectors;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.base.LlmMessage;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.base.StructuredOutput;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.conversation.pipeline.ConversationGenerationPipeline;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliFixedLines;
import com.yollo.TravelMate.domain.conversation.service.LiliPlanFailureReaction;
import com.yollo.TravelMate.domain.conversation.service.LiliTurns;
import com.yollo.TravelMate.domain.conversation.service.PreparedLinePlanFailureReaction;
import com.yollo.TravelMate.domain.plan.data.internal.PlanFailure;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class LiliPlanFailureReactionTest {
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();
    private final LlmClient llm = mock(LlmClient.class);
    private final LiliPlanFailureReaction reaction =
            new LiliPlanFailureReaction(new LiliTurns(ConversationGenerationPipeline.defaults(llm), mapper), mapper);

    @Test
    void liliHearsWhatTheServerSearchedAndWhatTheUserAskedButNoInternalCode() throws Exception {
        when(llm.chat(anyList(), anyList(), any(StructuredOutput.class))).thenReturn(LlmTurn.builder().content("""
                {"intent":"PLAN","emotion":"SAD","message":"종로 범위를 다 찾아봤는데 넣을 곳이 없었어. 범위를 넓혀서 다시 해 볼까?","choices":[]}""")
                .build());
        var cuts = reaction.execute(PlanFailure.NO_CANDIDATES_IN_AREA.classified(), request("조선 왕실 궁궐"));
        assertEquals(List.of(new DialogueCut("종로 범위를 다 찾아봤는데 넣을 곳이 없었어. 범위를 넓혀서 다시 해 볼까?", CharacterEmotion.SAD)), cuts);
        String sent = sent();
        assertTrue(sent.contains(PlanFailure.NO_CANDIDATES_IN_AREA.situation()), "she reacts to the verified fact");
        assertTrue(sent.contains("선택한 여행 범위에서 장소를 찾지 못했습니다."));
        assertTrue(sent.contains("조선 왕실 궁궐"), "she knows what the user wanted planned");
        assertFalse(sent.contains("NO_CANDIDATES_IN_AREA"), "the constant name stays on the server");
    }

    @Test
    void aRuleRejectionCarriesTheRulesOwnReasonToLili() throws Exception {
        when(llm.chat(anyList(), anyList(), any(StructuredOutput.class))).thenReturn(LlmTurn.builder().content("""
                {"intent":"PLAN","emotion":"CONCERNED","message":"시간이 모자라서 못 짰어.","choices":[]}""").build());
        var failure = PlanFailure.classify(new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                "방문 체류시간과 이동 여유를 합하면 여행 가능 시간을 초과합니다."));
        assertEquals(PlanFailure.CONDITION_REJECTED, failure.kind());
        reaction.execute(failure, request(null));
        assertTrue(sent().contains("방문 체류시간과 이동 여유를 합하면 여행 가능 시간을 초과합니다."));
    }

    @Test
    void anUnreadableReplyFallsBackToLilisPreparedLine() throws Exception {
        when(llm.chat(anyList(), anyList(), any(StructuredOutput.class))).thenReturn(LlmTurn.builder().content("not json").build());
        var cuts = reaction.execute(PlanFailure.DRAFT_REJECTED.classified(), request(null));
        assertEquals(List.of(LiliFixedLines.line(LiliFixedLines.Line.PLAN_UNAVAILABLE)), cuts);
    }

    @Test
    void eachFailureKindIsHandledByExactlyOneReaction() {
        var registry = List.of(reaction, new PreparedLinePlanFailureReaction());
        for (var kind : PlanFailure.values()) {
            assertEquals(1, registry.stream().filter(candidate -> candidate.supports(kind.reaction())).count(), kind.name());
        }
        assertNull(PlanFailure.GENERATION_UNAVAILABLE.situation(), "a failed model call is not explained by calling the model");
    }

    @Test
    void unknownCausesGetTheGenericMessageAndNoLiliExplanation() {
        var failure = PlanFailure.classify(new IllegalArgumentException("internal detail"));
        assertEquals(PlanFailure.UNEXPECTED, failure.kind());
        assertFalse(failure.userMessage().contains("internal detail"));
        assertEquals(PlanFailure.Reaction.FIXED_LINE, failure.kind().reaction());
    }

    private String sent() {
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<LlmMessage>> messages = ArgumentCaptor.forClass((Class<List<LlmMessage>>) (Class<?>) List.class);
        verify(llm).chat(messages.capture(), anyList(), any(StructuredOutput.class));
        return messages.getValue().stream().map(LlmMessage::content).collect(Collectors.joining("\n"));
    }

    private GeneratePlanRequest request(String searchQuery) throws Exception {
        var node = (ObjectNode) mapper.readTree(PlanContextContractTest.REQUEST);
        if (searchQuery != null) node.put("searchQuery", searchQuery);
        return mapper.treeToValue(node, GeneratePlanRequest.class);
    }
}
