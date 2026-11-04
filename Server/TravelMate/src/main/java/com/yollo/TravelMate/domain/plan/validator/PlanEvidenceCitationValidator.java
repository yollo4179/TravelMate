package com.yollo.TravelMate.domain.plan.validator;

import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.PreparedPrompt;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource;
import java.util.Map;

public final class PlanEvidenceCitationValidator {
    private PlanEvidenceCitationValidator() {}

    public static void validate(GeneratedPlan plan, PreparedPrompt prompt) {
        for (var pin : plan.pins()) {
            for (var citation : pin.citations()) {
                validate(pin.placeId(), citation, prompt.sources());
            }
        }
    }

    /** Returns the citation with the quote exactly as the original writes it; a quote from elsewhere is rejected. */
    public static GeneratedPlan.SourceCitation validate(
            long placeId,
            GeneratedPlan.SourceCitation citation,
            Map<String, CitationSource> sources
    ) {
        if (citation.evidenceId() == null || citation.sourceId() == null) {
            throw new IllegalStateException("인용에 출처 식별자가 없습니다.");
        }
        var source = sources.get(citation.evidenceId());
        if (source == null || source.placeId() != placeId || !source.evidence().sourceId().equals(citation.sourceId())) {
            throw new IllegalStateException("인용이 해당 장소에 실제 전달한 원문 근거에 속하지 않습니다.");
        }
        return source.evidence().originalQuote(placeId, citation.quote())
                .map(quote -> new GeneratedPlan.SourceCitation(citation.evidenceId(), citation.sourceId(), quote))
                .orElseThrow(() -> new IllegalStateException("인용이 해당 장소에 실제 전달한 원문 근거에 속하지 않습니다."));
    }
}
