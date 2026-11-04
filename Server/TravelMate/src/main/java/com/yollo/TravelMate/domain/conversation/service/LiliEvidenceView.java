package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.stream.StreamSupport;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * What LiLi's recommendation call may see of the searched places. A candidate without selected evidence is
 * kept only as a count: with its name or description in the prompt she named it, described it or cited its
 * description in live runs, and the prompt rule alone did not stop that.
 */
final class LiliEvidenceView {
    static final String CANDIDATES = "candidates";
    static final String CARD_ONLY_COUNT = "cardOnlyCandidateCount";
    static final String SHOWN_CARD_COUNT = "shownCardCount";
    private static final String SELECTED_EVIDENCE = "selectedEvidence";

    private LiliEvidenceView() {}

    static JsonNode of(JsonNode modelData) {
        if (modelData == null || !modelData.isObject()) return modelData;
        var candidates = StreamSupport.stream(modelData.path(CANDIDATES).spliterator(), false).toList();
        List<JsonNode> citable = candidates.stream().filter(LiliEvidenceView::hasEvidence)
                .<JsonNode>map(JsonNode::deepCopy).toList();
        ObjectNode view = modelData.deepCopy();
        ArrayNode kept = view.arrayNode().addAll(citable);
        view.set(CANDIDATES, kept);
        view.put(CARD_ONLY_COUNT, candidates.size() - citable.size());
        // With only an empty candidate list she said the search found nothing while ten cards were on screen.
        view.put(SHOWN_CARD_COUNT, candidates.size());
        return view;
    }

    private static boolean hasEvidence(JsonNode candidate) {
        return candidate.path(SELECTED_EVIDENCE).isArray() && !candidate.path(SELECTED_EVIDENCE).isEmpty();
    }
}
