package com.yollo.TravelMate.domain.plan.data.internal;

import org.springframework.web.server.ResponseStatusException;

/**
 * Why a draft job ended FAILED. The server decides the kind; LiLi only voices it. The user message stays the job's
 * error text for clients and operators, and the situation is the fact LiLi reacts to.
 */
public enum PlanFailure {
    // The search ran over the chosen area and returned nothing, so there was nothing to plan with.
    NO_CANDIDATES_IN_AREA(
            Reaction.LILI,
            "선택한 여행 범위에서 장소를 찾지 못했습니다.",
            "앱에서 고른 여행 범위 안의 장소 데이터를 찾아봤지만 일정에 넣을 장소가 하나도 없어서 일정을 만들지 않았다. "
                    + "범위를 넓히거나 위치를 바꿔 다시 요청할 수 있다."
    ),
    // A server rule refused the conditions or the draft; the rule's own reason is the user message.
    CONDITION_REJECTED(
            Reaction.LILI,
            null,
            "일정 조건이나 만든 초안을 서버 규칙으로 확인했더니 reason에 적힌 이유 때문에 일정을 저장하지 않았다."
    ),
    // The model answered, but its draft could not be read, so nothing was saved. Bad citations alone do not fail a draft.
    DRAFT_REJECTED(
            Reaction.LILI,
            "만들어진 초안이 확인 단계를 통과하지 못해 저장하지 않았어요. 다시 요청해 주세요.",
            "일정 초안을 만들었지만 확인 단계에서 읽을 수 없어 저장하지 않았다."
    ),
    // Budget guard, provider or transport: calling the model again for a reaction would meet the same failure.
    GENERATION_UNAVAILABLE(
            Reaction.FIXED_LINE,
            "일정 초안을 만들지 못했어요. 같은 조건으로 다시 요청하거나 조건을 바꿔 요청해 주세요.",
            null
    ),
    QUEUE_FULL(
            Reaction.FIXED_LINE,
            "생성 요청이 많습니다. 잠시 후 새 요청으로 시도해 주세요.",
            null
    ),
    // The cause is unknown to the user-facing layer, so LiLi is not asked to explain it.
    UNEXPECTED(
            Reaction.FIXED_LINE,
            "일정 생성 처리에 실패했습니다. 잠시 후 새 요청으로 시도해 주세요.",
            null
    );

    /** Who words the reaction: LiLi from the situation, or her prepared line when no model call should be made. */
    public enum Reaction { LILI, FIXED_LINE }

    /** The kind and the message users see for this one failure. */
    public record Classified(
            PlanFailure kind,
            String userMessage
    ) {}

    private final Reaction reaction;
    private final String userMessage;
    private final String situation;

    PlanFailure(
            Reaction reaction,
            String userMessage,
            String situation
    ) {
        this.reaction = reaction;
        this.userMessage = userMessage;
        this.situation = situation;
    }

    public Reaction reaction() {
        return reaction;
    }

    public String situation() {
        return situation;
    }

    public Classified classified() {
        return new Classified(this, userMessage);
    }

    public static Classified classify(Exception exception) {
        if (exception instanceof PlanFailureException known) return known.kind().classified();
        if (exception instanceof ResponseStatusException rule) return new Classified(CONDITION_REJECTED, rule.getReason());
        // Known business errors already carry a message written for users; their cause is still not LiLi's to explain.
        if (exception instanceof com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException known) {
            return new Classified(UNEXPECTED, known.getErrorCode().getMessage());
        }
        return UNEXPECTED.classified();
    }

    /** Raised inside a draft job when the server has already decided which failure it is. */
    public static final class PlanFailureException extends RuntimeException {
        private final PlanFailure kind;

        public PlanFailureException(PlanFailure kind) {
            super(kind.name());
            this.kind = kind;
        }

        public PlanFailureException(
                PlanFailure kind,
                Throwable cause
        ) {
            super(kind.name(), cause);
            this.kind = kind;
        }

        public PlanFailure kind() {
            return kind;
        }
    }
}
