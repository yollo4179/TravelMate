package com.yollo.TravelMate.domain.place.client;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.yollo.TravelMate.config.observability.SearchTracing;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService.RankingMode;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.Context;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@Component
public class PlaceSemanticSearchClient {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final TransactionTemplate transactionTemplate;
    private final SearchTracing searchTracing;
    private final String requestTopic;
    private final long timeoutSeconds;
    private final ConcurrentHashMap<UUID, CompletableFuture<List<PlaceSemanticSearchResult>>> pendingRequests =
            new ConcurrentHashMap<>();

    public PlaceSemanticSearchClient(
            JdbcTemplate jdbcTemplate,
            ObjectMapper objectMapper,
            TransactionTemplate transactionTemplate,
            SearchTracing searchTracing,
            @Value("${travelmate.kafka.recommendation-requests-topic:travelmate.recommendation-requests.v1}")
            String requestTopic,
            @Value("${travelmate.kafka.recommendation-timeout-seconds:120}") long timeoutSeconds
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
        this.transactionTemplate = transactionTemplate;
        this.searchTracing = searchTracing;
        this.requestTopic = requestTopic;
        this.timeoutSeconds = timeoutSeconds;
    }

    public List<PlaceSemanticSearchResult> search(
            String query,
            String region,
            String city,
            String category,
            int limit,
            PlanContext.Area area,
            RankingMode rankingMode
    ) {
        UUID requestId = UUID.randomUUID();
        CompletableFuture<List<PlaceSemanticSearchResult>> resultFuture = new CompletableFuture<>();
        pendingRequests.put(requestId, resultFuture);

        try {
            ObjectNode request = buildRequest(requestId, query, region, city, category, limit, area, rankingMode);
            String payload = objectMapper.writeValueAsString(request);
            persistRequest(requestId, request.path("context_version").asLong(), payload);
            return searchTracing.trace("recommendation.kafka_roundtrip", () -> {
                Span span = Span.current();
                span.setAttribute("messaging.system", "kafka");
                span.setAttribute("messaging.destination.name", requestTopic);
                span.setAttribute("search.query", query);
                span.setAttribute("search.ranking_mode", rankingMode.name());
                span.setAttribute("search.limit", limit);
                setAttributeIfPresent(span, "search.region", region);
                setAttributeIfPresent(span, "search.city", city);
                setAttributeIfPresent(span, "search.category", category);
                try {
                    List<PlaceSemanticSearchResult> results = resultFuture.get(timeoutSeconds, TimeUnit.SECONDS);
                    setResultAttributes(span, results);
                    return results;
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException("추천 결과 대기가 중단되었습니다.", exception);
                } catch (ExecutionException | TimeoutException exception) {
                    throw new IllegalStateException("추천 결과를 제한 시간 안에 받지 못했습니다.", exception);
                }
            });
        } catch (Exception exception) {
            throw new IllegalStateException("Kafka 추천 요청을 완료하지 못했습니다. requestId=" + requestId, exception);
        } finally {
            pendingRequests.remove(requestId);
        }
    }

    @KafkaListener(
            topics = "${travelmate.kafka.recommendation-results-topic:travelmate.recommendation-results.v1}",
            groupId = "travelmate-spring-recommendation-results-v1"
    )
    public void receiveResult(String message) {
        try {
            JsonNode result = objectMapper.readTree(message);
            UUID requestId = UUID.fromString(result.path("request_id").asText());
            UUID eventId = UUID.fromString(result.path("event_id").asText());
            String eventType = result.path("event_type").asText();
            List<PlaceSemanticSearchResult> items = "RECOMMENDATION_COMPLETED".equals(eventType)
                    ? parseResults(result.path("items"))
                    : List.of();
            persistResult(requestId, eventId, message, "RECOMMENDATION_COMPLETED".equals(eventType));

            CompletableFuture<List<PlaceSemanticSearchResult>> resultFuture = pendingRequests.get(requestId);
            if (resultFuture == null) {
                log.info("요청 대기가 끝난 뒤 추천 결과를 영속 수신했습니다. requestId={}", requestId);
                return;
            }
            if ("RECOMMENDATION_COMPLETED".equals(eventType)) {
                resultFuture.complete(items);
            } else {
                resultFuture.completeExceptionally(new IllegalStateException(
                        "추천 작업에 실패했습니다: " + result.path("error_code").asText("UNKNOWN")
                ));
            }
        } catch (Exception exception) {
            log.error("추천 완료 메시지 처리에 실패했습니다.", exception);
            throw new IllegalStateException("추천 완료 메시지를 영속 처리하지 못했습니다.", exception);
        }
    }

    private void persistRequest(UUID requestId, long contextVersion, String payload) {
        String eventId;
        try {
            eventId = objectMapper.readTree(payload).path("event_id").asText();
        } catch (Exception exception) {
            throw new IllegalStateException("추천 요청 이벤트 ID를 읽지 못했습니다.", exception);
        }
        transactionTemplate.executeWithoutResult(status -> {
            jdbcTemplate.update(
                    """
                    INSERT INTO recommendation_requests (request_id, context_version, request_payload)
                    VALUES (?::uuid, ?, ?::jsonb)
                    """,
                    requestId.toString(),
                    contextVersion,
                    payload
            );
            jdbcTemplate.update(
                    """
                    INSERT INTO recommendation_request_outbox (event_id, request_id, payload)
                    VALUES (?::uuid, ?::uuid, ?::jsonb)
                    """,
                    eventId,
                    requestId.toString(),
                    payload
            );
        });
    }

    private void persistResult(UUID requestId, UUID eventId, String payload, boolean completed) {
        transactionTemplate.executeWithoutResult(status -> {
            int stored = jdbcTemplate.update(
                    """
                    INSERT INTO recommendation_result_inbox (event_id, request_id, payload)
                    VALUES (?::uuid, ?::uuid, ?::jsonb)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    eventId.toString(),
                    requestId.toString(),
                    payload
            );
            if (stored == 0) {
                return;
            }
            int updated = jdbcTemplate.update(
                    """
                    UPDATE recommendation_requests
                    SET status = ?, result_payload = ?::jsonb, updated_at = now()
                    WHERE request_id = ?::uuid
                    """,
                    completed ? "COMPLETED" : "FAILED",
                    payload,
                    requestId.toString()
            );
            if (updated != 1) {
                throw new IllegalStateException("저장된 추천 요청이 없는 완료 메시지입니다: " + requestId);
            }
        });
    }

    private ObjectNode buildRequest(
            UUID requestId,
            String query,
            String region,
            String city,
            String category,
            int limit,
            PlanContext.Area area,
            RankingMode rankingMode
    ) {
        ObjectNode request = objectMapper.createObjectNode();
        request.put("schema_version", 1);
        request.put("event_id", UUID.randomUUID().toString());
        request.put("event_type", "RECOMMENDATION_REQUESTED");
        request.put("request_id", requestId.toString());
        request.put("context_version", 0);
        request.put("requested_at", Instant.now().toString());
        request.putNull("deadline_at");
        request.put("query", query);
        Map<String, String> traceHeaders = new java.util.HashMap<>();
        W3CTraceContextPropagator.getInstance().inject(Context.current(), traceHeaders, Map::put);
        if (traceHeaders.containsKey("traceparent")) {
            request.put("traceparent", traceHeaders.get("traceparent"));
        }
        if (traceHeaders.containsKey("tracestate")) {
            request.put("tracestate", traceHeaders.get("tracestate"));
        }
        ObjectNode filters = request.putObject("filters");
        putNullable(filters, "region", region);
        putNullable(filters, "city", city);
        putNullable(filters, "category", category);
        if (area == null) {
            filters.putNull("area");
        } else {
            ObjectNode areaNode = filters.putObject("area");
            areaNode.put("type", area.type().name());
            if (area.center() == null) {
                areaNode.putNull("center");
            } else {
                areaNode.putObject("center")
                        .put("lat", area.center().lat())
                        .put("lon", area.center().lon());
            }
            if (area.radiusMeters() == null) {
                areaNode.putNull("radius_meters");
            } else {
                areaNode.put("radius_meters", area.radiusMeters());
            }
        }
        filters.putArray("exclude_place_ids");
        request.put("ranking_mode", rankingMode.name());
        request.put("limit", limit);
        return request;
    }

    private void setResultAttributes(Span span, List<PlaceSemanticSearchResult> results) {
        span.setAttribute("search.returned_count", results.size());
        span.setAttribute("reranking.applied_count", results.stream()
                .filter(result -> result.rerankScore() != null)
                .count());

        var resultPreview = objectMapper.createArrayNode();
        results.forEach(result -> {
            PlaceResult place = result.place();
            ObjectNode item = resultPreview.addObject();
            item.put("id", place.id());
            item.put("name", place.name());
            item.put("semantic_score", place.similarity());
            if (result.rerankScore() == null) {
                item.putNull("rerank_score");
            } else {
                item.put("rerank_score", result.rerankScore());
            }
        });
        span.setAttribute("search.results_preview", resultPreview.toString());
    }

    private static void setAttributeIfPresent(Span span, String key, String value) {
        if (value != null && !value.isBlank()) {
            span.setAttribute(key, value);
        }
    }

    private List<PlaceSemanticSearchResult> parseResults(JsonNode items) {
        if (!items.isArray()) {
            throw new IllegalStateException("추천 완료 결과에 items 목록이 없습니다.");
        }
        List<PlaceSemanticSearchResult> results = new ArrayList<>(items.size());
        HashSet<Long> placeIds = new HashSet<>();
        int expectedRank = 1;
        for (JsonNode item : items) {
            long placeId = item.path("place_id").asLong(-1);
            int rank = item.path("rank").asInt(-1);
            if (placeId < 0 || rank != expectedRank++ || !placeIds.add(placeId)) {
                throw new IllegalStateException("추천 완료 결과의 ID 또는 순위가 올바르지 않습니다.");
            }
            double semanticScore = item.path("semantic_score").asDouble(Double.NaN);
            Float rerankScore = item.path("rerank_score").isNumber()
                    ? (float) item.path("rerank_score").asDouble()
                    : null;
            if (!Double.isFinite(semanticScore) || (rerankScore != null && !Float.isFinite(rerankScore))) {
                throw new IllegalStateException("추천 완료 결과에 유효하지 않은 점수가 포함되어 있습니다.");
            }
            PlaceResult place = new PlaceResult(
                    placeId,
                    nullableText(item, "name"),
                    nullableText(item, "description"),
                    nullableText(item, "region"),
                    nullableText(item, "city"),
                    nullableText(item, "category"),
                    nullableText(item, "source_category"),
                    nullableDouble(item, "latitude"),
                    nullableDouble(item, "longitude"),
                    semanticScore,
                    nullableText(item, "tour_content_id"),
                    nullableText(item, "image_url"),
                    nullableText(item, "homepage_url")
            );
            results.add(new PlaceSemanticSearchResult(place, rerankScore));
        }
        return List.copyOf(results);
    }

    private static void putNullable(ObjectNode node, String name, String value) {
        if (value == null) {
            node.putNull(name);
            return;
        }
        node.put(name, value);
    }

    private static String nullableText(JsonNode node, String fieldName) {
        JsonNode value = node.get(fieldName);
        return value == null || value.isNull() ? null : value.asText();
    }

    private static Double nullableDouble(JsonNode node, String fieldName) {
        JsonNode value = node.get(fieldName);
        return value == null || value.isNull() ? null : value.asDouble();
    }
}
