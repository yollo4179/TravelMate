package com.yollo.TravelMate;

import java.nio.charset.StandardCharsets;
import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

final class SearchEvidenceFixtures {
    static final String WALK = "A공원에서 계단을 내려가 B공원까지 걸어갔다.";
    static final String BLOCK = "A공원에서 B공원으로 이동하려 했지만 공사로 길이 막혀 돌아왔다.";
    static final String ORIGINAL = "🌙 A공원의 야경을 봤다는 방문 기록. ".repeat(35) + WALK
            + " 다만 과거 방문 경험이며 현재도 통행할 수 있다는 뜻은 아니다.";
    static final String SUPPLEMENT = "현재 항상 무료 개방이며 모든 시설이 완비되어 있다.";

    private SearchEvidenceFixtures() {}

    static ObjectNode chunk(ObjectMapper mapper, String text, String relationQuote) {
        String sourceId = UUID.nameUUIDFromBytes(text.getBytes(StandardCharsets.UTF_8)).toString();
        ObjectNode chunk = mapper.createObjectNode();
        chunk.put("chunk_id", UUID.nameUUIDFromBytes(("chunk:" + text).getBytes(StandardCharsets.UTF_8)).toString());
        chunk.put("context_version", "context-v1");
        chunk.put("source_id", sourceId);
        chunk.put("source_version", "source-v1");
        chunk.put("source_type", "review");
        chunk.put("title", "합성 근거 전달 검증");
        chunk.put("content_kind", "landscape");
        chunk.put("chunk_text", text);
        chunk.put("context_text", SUPPLEMENT);
        chunk.putArray("hypothetical_questions").add("생성된 보충 질문");
        chunk.putArray("entities");
        chunk.putObject("generation").put("provider", "synthetic-test");
        chunk.putObject("metadata").put("source_url", "https://example.org/" + sourceId)
                .put("published_at", "2024-01-01").put("preserved_extra", "원본 metadata도 유지");
        int sourceStart = 10;
        chunk.putObject("source_span").put("start", sourceStart)
                .put("end", sourceStart + text.codePointCount(0, text.length())).put("unit", "unicode_codepoint");
        ArrayNode references = chunk.putArray("place_refs");
        references.addObject().put("place_id", 101).put("role", "subject");
        references.addObject().put("place_id", 202).put("role", "mentioned");
        int quoteStart = sourceStart + text.codePointCount(0, text.indexOf(relationQuote));
        ObjectNode relation = chunk.putArray("relations").addObject();
        relation.put("type", "movement").put("importance", "supporting");
        relation.putObject("origin").put("place_id", 101).put("name", "A공원");
        relation.putObject("destination").put("place_id", 202).put("name", "B공원");
        relation.putObject("evidence").put("start", quoteStart)
                .put("end", quoteStart + relationQuote.codePointCount(0, relationQuote.length())).put("quote", relationQuote);
        relation.putArray("conditions");
        return chunk;
    }

    static ObjectNode event(ObjectMapper mapper) {
        ObjectNode event = mapper.createObjectNode();
        event.put("request_id", UUID.randomUUID().toString()).put("event_id", UUID.randomUUID().toString())
                .put("event_type", "RECOMMENDATION_COMPLETED");
        ObjectNode item = event.putArray("items").addObject();
        item.put("place_id", 101).put("rank", 1).put("name", "A공원").put("description", ORIGINAL)
                .put("semantic_score", 0.9).put("rerank_score", 0.8).put("category", "카페")
                .put("latitude", 35.8395).put("longitude", 129.212);
        var positive = chunk(mapper, ORIGINAL, WALK);
        ((ArrayNode) positive.path("relations").get(0).get("conditions")).addObject()
                .put("kind", "stairs").put("quote", "계단을 내려가");
        var blocked = chunk(mapper, BLOCK, BLOCK);
        ((ArrayNode) blocked.path("relations").get(0).get("conditions")).addObject()
                .put("kind", "other").put("quote", "공사로 길이 막혀");
        item.putArray("evidence_chunks").add(positive).add(blocked);
        return event;
    }
}
