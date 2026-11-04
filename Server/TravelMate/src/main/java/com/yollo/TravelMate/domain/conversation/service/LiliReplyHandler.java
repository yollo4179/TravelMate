package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Set;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** Chat and clarification end with LiLi's own cut; no search and no tool. */
@Component
@RequiredArgsConstructor
public class LiliReplyHandler implements LiliBranchHandler {
    private static final Set<LiliBranch> BRANCHES = Set.of(LiliBranch.CHAT, LiliBranch.CLARIFY);
    private final ConversationAnswerRenderer renderer;

    @Override
    public boolean supports(LiliBranch branch) {
        return BRANCHES.contains(branch);
    }

    @Override
    public ConversationResponse execute(Input input) {
        var decision = input.decision();
        return renderer.dialogue(
                null,
                decision.intent(),
                List.of(),
                List.of(decision.cut()),
                decision.choices(),
                Termination.COMPLETED,
                1,
                List.of()
        );
    }
}
