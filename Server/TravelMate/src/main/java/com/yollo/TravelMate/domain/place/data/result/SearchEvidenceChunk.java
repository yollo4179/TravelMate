package com.yollo.TravelMate.domain.place.data.result;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;
import com.fasterxml.jackson.databind.JsonNode;

/** 원문을 재작성하지 않는 Kafka 근거 값. 형식 검증은 의미 적합성 판정이 아니다. */
public final class SearchEvidenceChunk {
    private enum RetrievalScope { RELATION }
    private enum PlaceRole { SUBJECT }
    private enum CoordinateUnit { UNICODE_CODEPOINT }
    private final JsonNode document;

    @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
    public SearchEvidenceChunk(JsonNode document) {
        if (document == null || !document.isObject()) {
            throw new IllegalArgumentException("검색 근거는 객체여야 합니다.");
        }
        this.document = document.deepCopy();
        for (String field : List.of("chunk_id", "context_version", "source_id", "source_version", "chunk_text")) {
            requireText(this.document, field);
        }
        validateSpan();
        validateRelations();
    }

    public static List<SearchEvidenceChunk> parse(JsonNode chunks) {
        if (chunks == null || chunks.isMissingNode() || chunks.isNull()) return List.of();
        if (!chunks.isArray()) throw new IllegalArgumentException("evidence_chunks는 배열이어야 합니다.");
        List<SearchEvidenceChunk> selected = new ArrayList<>();
        chunks.forEach(chunk -> selected.add(new SearchEvidenceChunk(chunk)));
        return List.copyOf(selected);
    }

    @JsonValue
    public JsonNode toJson() {
        return document.deepCopy();
    }

    public String sourceId() {
        return document.get("source_id").textValue();
    }

    public boolean permitsQuote(long placeId, String quote) {
        if (quote == null || quote.isBlank()) return false;
        boolean relationOnly = document.path("retrieval_scope").asText().equals(RetrievalScope.RELATION.name().toLowerCase(Locale.ROOT))
                || document.has("retrieved_relation_index");
        if (!relationOnly && isObservationSubject(placeId)) {
            return document.get("chunk_text").textValue().contains(quote);
        }
        for (JsonNode relation : selectedRelations()) {
            boolean participant = relation.path("origin").path("place_id").asLong(-1) == placeId
                    || relation.path("destination").path("place_id").asLong(-1) == placeId;
            JsonNode evidence = relation.path("evidence");
            if (participant && evidence.path("quote").isTextual() && evidence.get("quote").textValue().contains(quote)) {
                return true;
            }
        }
        return false;
    }

    private boolean isObservationSubject(long placeId) {
        for (JsonNode reference : document.path("place_refs")) {
            if (reference.path("place_id").asLong(-1) == placeId
                    && reference.path("role").asText().equals(PlaceRole.SUBJECT.name().toLowerCase(Locale.ROOT))) {
                return true;
            }
        }
        return false;
    }

    private List<JsonNode> selectedRelations() {
        List<JsonNode> relations = new ArrayList<>();
        document.path("relations").forEach(relations::add);
        if (document.has("retrieved_relation_index")) {
            int index = document.get("retrieved_relation_index").intValue();
            return List.of(relations.get(index));
        }
        if (document.has("matched_relations")) {
            List<JsonNode> matched = new ArrayList<>();
            document.get("matched_relations").forEach(matched::add);
            return List.copyOf(matched);
        }
        return List.copyOf(relations);
    }

    private void validateSpan() {
        JsonNode span = document.path("source_span");
        int start = coordinate(span, "start");
        int end = coordinate(span, "end");
        String text = document.get("chunk_text").textValue();
        if (!span.path("unit").asText().equals(CoordinateUnit.UNICODE_CODEPOINT.name().toLowerCase(Locale.ROOT)) || start < 0 || end <= start
                || end - start != text.codePointCount(0, text.length())) {
            throw new IllegalArgumentException("검색 원문의 좌표와 길이가 일치하지 않습니다.");
        }
        if (!document.path("place_refs").isArray()) {
            throw new IllegalArgumentException("검색 원문의 장소 귀속 목록이 없습니다.");
        }
    }

    private void validateRelations() {
        JsonNode relations = document.path("relations");
        if (!relations.isMissingNode() && !relations.isArray()) {
            throw new IllegalArgumentException("관계 근거는 배열이어야 합니다.");
        }
        for (JsonNode relation : relations) {
            JsonNode evidence = relation.get("evidence");
            if (evidence == null) continue;
            String quote = requireText(evidence, "quote");
            int sourceStart = document.get("source_span").get("start").intValue();
            int sourceEnd = document.get("source_span").get("end").intValue();
            int quoteStart = coordinate(evidence, "start");
            int quoteEnd = coordinate(evidence, "end");
            if (quoteStart < sourceStart || quoteEnd > sourceEnd) {
                throw new IllegalArgumentException("관계 인용이 전달된 청크 밖에 있습니다.");
            }
            int start = quoteStart - sourceStart;
            int end = quoteEnd - sourceStart;
            String text = document.get("chunk_text").textValue();
            int length = text.codePointCount(0, text.length());
            if (start < 0 || end <= start || end > length
                    || !text.substring(text.offsetByCodePoints(0, start), text.offsetByCodePoints(0, end)).equals(quote)) {
                throw new IllegalArgumentException("관계 인용이 전달된 원문 좌표와 일치하지 않습니다.");
            }
            for (JsonNode condition : relation.path("conditions")) {
                if (!quote.contains(requireText(condition, "quote"))) {
                    throw new IllegalArgumentException("관계 조건이 인용에 속하지 않습니다.");
                }
            }
        }
        if (document.has("matched_relations")) {
            if (!document.get("matched_relations").isArray()) throw new IllegalArgumentException("선택 관계가 배열이 아닙니다.");
            for (JsonNode matched : document.get("matched_relations")) {
                boolean found = false;
                for (JsonNode relation : relations) found |= relation.equals(matched);
                if (!found) throw new IllegalArgumentException("선택 관계가 원래 관계 목록에 없습니다.");
            }
        }
        if (document.has("retrieved_relation_index")) {
            int index = coordinate(document, "retrieved_relation_index");
            if (index < 0 || index >= relations.size()
                    || (document.has("matched_relations") && !contains(document.get("matched_relations"), relations.get(index)))) {
                throw new IllegalArgumentException("검색한 관계 순번이 선택 근거와 다릅니다.");
            }
        }
    }

    private static boolean contains(JsonNode values, JsonNode expected) {
        for (JsonNode value : values) if (value.equals(expected)) return true;
        return false;
    }

    private static int coordinate(JsonNode parent, String field) {
        JsonNode value = parent.path(field);
        if (!value.isIntegralNumber() || !value.canConvertToInt()) {
            throw new IllegalArgumentException("인용 좌표는 정수여야 합니다.");
        }
        return value.intValue();
    }

    private static String requireText(JsonNode parent, String field) {
        JsonNode value = parent.path(field);
        if (!value.isTextual() || value.textValue().isBlank()) {
            throw new IllegalArgumentException("검색 근거 필드가 비어 있습니다: " + field);
        }
        return value.textValue();
    }
}
