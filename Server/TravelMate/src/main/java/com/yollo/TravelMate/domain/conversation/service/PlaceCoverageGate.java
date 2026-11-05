package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Optional;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliFixedLines;
import com.yollo.TravelMate.domain.place.data.internal.Sido;
import com.yollo.TravelMate.domain.place.data.result.PlaceCoverage;
import com.yollo.TravelMate.domain.place.service.PlaceCoverageService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * An area the place data does not hold ends with LiLi's prepared line instead of a search that can only return other
 * areas. LiLi only names the area; whether the data holds it is read from the data, so her guesses about what exists
 * (live runs: "switch the range to Busan") never reach the user.
 */
@Component
@RequiredArgsConstructor
public class PlaceCoverageGate {
    private final PlaceCoverageService coverage;
    private final ConversationAnswerRenderer renderer;
    private final ObjectMapper mapper;

    public Optional<ConversationResponse> outside(LiliTurns.Decision decision) {
        var current = coverage.current();
        return Optional.ofNullable(decision.requestedRegion())
                .filter(region -> decision.branch().asksForPlacesInWords())
                .filter(current::excludes)
                .map(region -> refuse(decision, region, current));
    }

    private ConversationResponse refuse(
            LiliTurns.Decision decision,
            Sido region,
            PlaceCoverage current
    ) {
        var event = mapper.createObjectNode().put("requestedRegion", region.label()).put("branch", decision.branch().name());
        var covered = event.putArray("coveredRegions");
        current.regionLabels().forEach(covered::add);
        ObservationContext.record(ObservationContext.Event.COVERAGE, event);
        var line = LiliFixedLines.outsideCoverage(region.label(), String.join("·", current.regionLabels()),
                String.join("·", current.categories()));
        return renderer.dialogue(null, decision.intent(), List.of(), List.of(line), List.of(), Termination.COMPLETED, 1, List.of());
    }
}
