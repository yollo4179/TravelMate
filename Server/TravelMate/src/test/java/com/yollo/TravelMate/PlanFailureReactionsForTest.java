package com.yollo.TravelMate;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.plan.data.internal.PlanFailure;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.service.PlanFailureReaction;

/** One reaction per kind that records what it was asked, for planning tests that do not call LiLi's model. */
final class PlanFailureReactionsForTest {
    static final DialogueCut LILI_CUT = new DialogueCut("범위 안을 찾아봤는데 넣을 곳이 없었어.", CharacterEmotion.SAD);
    static final DialogueCut PREPARED_CUT = new DialogueCut("미안, 이번엔 일정 초안을 만들지 못했어.", CharacterEmotion.CONCERNED);

    final List<PlanFailure.Classified> asked = new CopyOnWriteArrayList<>();

    List<PlanFailureReaction> registry() {
        return List.of(recording(PlanFailure.Reaction.LILI, LILI_CUT), recording(PlanFailure.Reaction.FIXED_LINE, PREPARED_CUT));
    }

    private PlanFailureReaction recording(
            PlanFailure.Reaction handled,
            DialogueCut cut
    ) {
        return new PlanFailureReaction() {
            @Override
            public boolean supports(PlanFailure.Reaction reaction) {
                return reaction == handled;
            }

            @Override
            public List<DialogueCut> execute(
                    PlanFailure.Classified failure,
                    GeneratePlanRequest request
            ) {
                asked.add(failure);
                return List.of(cut);
            }
        };
    }
}
