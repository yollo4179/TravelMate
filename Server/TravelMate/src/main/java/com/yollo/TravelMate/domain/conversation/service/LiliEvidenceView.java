package com.yollo.TravelMate.domain.conversation.service;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.StreamSupport;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * What LiLi's recommendation call may see of the searched places. A candidate without selected evidence is
 * kept only as a count: with its name or description in the prompt she named it, described it or cited its
 * description in live runs, and the prompt rule alone did not stop that.
 * <p>
 * The citable candidates also lose what the model cannot use: SHA-256 provenance hashes (216 tokens for one place
 * in a live run) and the card summary, which repeats the start of the original she cites (286 tokens there).
 * Provenance stays in the EVIDENCE_PREPARATION event; citation checks use evidenceId and sourceId, which are kept.
 */
final class LiliEvidenceView {
    static final String CANDIDATES = "candidates";
    static final String CARD_ONLY_COUNT = "cardOnlyCandidateCount";
    static final String SHOWN_CARD_COUNT = "shownCardCount";
    private static final String SELECTED_EVIDENCE = "selectedEvidence";
    private static final String CARD_SUMMARY = "description";
    private static final Pattern SHA256_HEX = Pattern.compile("[0-9a-f]{64}");

    private LiliEvidenceView() {}

    static JsonNode of(JsonNode modelData) {
        if (modelData == null || !modelData.isObject()) return modelData;
        var candidates = StreamSupport.stream(modelData.path(CANDIDATES).spliterator(), false).toList();
        List<JsonNode> citable = candidates.stream().filter(LiliEvidenceView::hasEvidence)
                .<JsonNode>map(LiliEvidenceView::forLili).toList();
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

    private static JsonNode forLili(JsonNode candidate) {
        ObjectNode copy = candidate.deepCopy();
        copy.remove(CARD_SUMMARY);
        copy.path(SELECTED_EVIDENCE).forEach(LiliEvidenceView::dropHashes);
        return copy;
    }

    private static void dropHashes(JsonNode node) {
        if (node instanceof ObjectNode object) {
            var hashed = new ArrayList<String>();
            object.fields().forEachRemaining(field -> {
                if (field.getValue().isTextual() && SHA256_HEX.matcher(field.getValue().textValue()).matches()) hashed.add(field.getKey());
            });
            object.remove(hashed);
            object.forEach(LiliEvidenceView::dropHashes);
        } else if (node.isArray()) {
            node.forEach(LiliEvidenceView::dropHashes);
        }
    }
}
