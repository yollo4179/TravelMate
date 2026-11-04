package com.yollo.TravelMate.domain.plan.validator;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.PreparedPrompt;

public final class PlanEvidenceCitationValidator {
    /** Why a citation was not accepted; the message is for operators and logs, never for users. */
    public enum Rejection {
        MISSING_IDENTIFIERS("인용에 출처 식별자가 없습니다."),
        NOT_DELIVERED_FOR_PLACE("인용이 해당 장소에 실제 전달한 원문 근거에 속하지 않습니다."),
        QUOTE_NOT_IN_ORIGINAL("인용 문장이 전달한 원문에 그대로 있지 않습니다.");

        private final String message;

        Rejection(String message) {
            this.message = message;
        }

        public String message() {
            return message;
        }
    }

    public record Dropped(long placeId, GeneratedPlan.SourceCitation citation, Rejection reason) {}

    /** The plan with only verified citations, each quote copied from the original, and what was taken out. */
    public record Review(GeneratedPlan plan, List<Dropped> dropped) {
        public Review {
            dropped = List.copyOf(dropped);
        }
    }

    private PlanEvidenceCitationValidator() {}

    /** Strict form: any citation that fails verification rejects the whole plan. */
    public static void validate(GeneratedPlan plan, PreparedPrompt prompt) {
        review(plan, prompt).dropped().stream().findFirst().ifPresent(first -> {
            throw new IllegalStateException(first.reason().message());
        });
    }

    /**
     * Keeps the draft and removes only citations that fail verification, as answer-attribution checks usually do:
     * a mis-copied quote costs its source mark, not the whole plan. Pin citations are a gate and are not shown to
     * users, so removing one changes nothing they see; the removals are returned so they can be recorded.
     */
    public static Review review(GeneratedPlan plan, PreparedPrompt prompt) {
        var dropped = new ArrayList<Dropped>();
        var pins = plan.pins().stream().map(pin -> new GeneratedPlan.GeneratedPin(
                pin.placeId(),
                pin.sequence(),
                pin.activity(),
                pin.reason(),
                pin.citations().stream()
                        .map(citation -> verified(pin.placeId(), citation, prompt.sources(), dropped))
                        .flatMap(Optional::stream)
                        .toList()
        )).toList();
        var reviewed = new GeneratedPlan(plan.planTitle(), plan.planDescription(), pins, plan.dialogue());
        return new Review(reviewed, dropped);
    }

    /** Returns the citation with the quote exactly as the original writes it; a quote from elsewhere is rejected. */
    public static GeneratedPlan.SourceCitation validate(
            long placeId,
            GeneratedPlan.SourceCitation citation,
            Map<String, CitationSource> sources
    ) {
        var dropped = new ArrayList<Dropped>();
        return verified(placeId, citation, sources, dropped)
                .orElseThrow(() -> new IllegalStateException(dropped.get(0).reason().message()));
    }

    private static Optional<GeneratedPlan.SourceCitation> verified(
            long placeId,
            GeneratedPlan.SourceCitation citation,
            Map<String, CitationSource> sources,
            List<Dropped> dropped
    ) {
        if (citation.evidenceId() == null || citation.sourceId() == null) {
            dropped.add(new Dropped(placeId, citation, Rejection.MISSING_IDENTIFIERS));
            return Optional.empty();
        }
        var source = sources.get(citation.evidenceId());
        if (source == null || source.placeId() != placeId || !source.evidence().sourceId().equals(citation.sourceId())) {
            dropped.add(new Dropped(placeId, citation, Rejection.NOT_DELIVERED_FOR_PLACE));
            return Optional.empty();
        }
        var quote = source.evidence().originalQuote(placeId, citation.quote());
        if (quote.isEmpty()) {
            dropped.add(new Dropped(placeId, citation, Rejection.QUOTE_NOT_IN_ORIGINAL));
            return Optional.empty();
        }
        return quote.map(original -> new GeneratedPlan.SourceCitation(citation.evidenceId(), citation.sourceId(), original));
    }
}
