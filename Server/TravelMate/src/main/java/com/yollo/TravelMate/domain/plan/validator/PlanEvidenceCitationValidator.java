package com.yollo.TravelMate.domain.plan.validator;

import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.PreparedPrompt;

public final class PlanEvidenceCitationValidator {
    private PlanEvidenceCitationValidator() {}

    public static void validate(GeneratedPlan plan, PreparedPrompt prompt) {
        for (var pin : plan.pins()) {
            for (var citation : pin.citations()) {
                if (citation.evidenceId() == null || citation.sourceId() == null) {
                    throw new IllegalStateException("인용에 출처 식별자가 없습니다.");
                }
                var source = prompt.sources().get(citation.evidenceId());
                if (source == null || source.placeId() != pin.placeId()
                        || !source.evidence().sourceId().equals(citation.sourceId())
                        || !source.evidence().permitsQuote(pin.placeId(), citation.quote())) {
                    throw new IllegalStateException("인용이 해당 장소에 실제 전달한 원문 근거에 속하지 않습니다.");
                }
            }
        }
    }
}
