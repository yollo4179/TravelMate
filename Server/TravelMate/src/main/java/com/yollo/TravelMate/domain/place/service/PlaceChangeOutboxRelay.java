package com.yollo.TravelMate.domain.place.service;

import java.util.List;
import java.util.concurrent.TimeUnit;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import lombok.extern.slf4j.Slf4j;

@Slf4j
@Component
public class PlaceChangeOutboxRelay {

    private final JdbcTemplate jdbcTemplate;
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final String placeChangesTopic;
    private final String recommendationRequestsTopic;

    public PlaceChangeOutboxRelay(
            JdbcTemplate jdbcTemplate,
            KafkaTemplate<String, String> kafkaTemplate,
            @Value("${travelmate.kafka.place-changes-topic:travelmate.place-changes.v1}") String placeChangesTopic,
            @Value("${travelmate.kafka.recommendation-requests-topic:travelmate.recommendation-requests.v1}")
            String recommendationRequestsTopic
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.kafkaTemplate = kafkaTemplate;
        this.placeChangesTopic = placeChangesTopic;
        this.recommendationRequestsTopic = recommendationRequestsTopic;
    }

    @Scheduled(fixedDelayString = "${travelmate.kafka.outbox-relay-delay-ms:1000}")
    public void relayOutboxEvents() {
        relayPlaceChanges();
        relayRecommendationRequests();
    }

    private void relayPlaceChanges() {
        List<OutboxEvent> events = jdbcTemplate.query(
                """
                SELECT event_id::text, place_id::text AS message_key, payload::text
                FROM place_change_outbox
                WHERE published_at IS NULL
                ORDER BY created_at
                LIMIT 50
                """,
                (resultSet, rowNumber) -> new OutboxEvent(
                        resultSet.getString("event_id"),
                        resultSet.getString("message_key"),
                        resultSet.getString("payload")
                )
        );
        for (OutboxEvent event : events) {
            try {
                kafkaTemplate.send(placeChangesTopic, event.messageKey(), event.payload()).get(10, TimeUnit.SECONDS);
                jdbcTemplate.update(
                        "UPDATE place_change_outbox SET published_at = now() WHERE event_id = ?::uuid",
                        event.eventId()
                );
            } catch (Exception exception) {
                log.warn("Place change event publish will retry: eventId={}", event.eventId(), exception);
                return;
            }
        }
    }

    private void relayRecommendationRequests() {
        List<OutboxEvent> events = jdbcTemplate.query(
                """
                SELECT event_id::text, request_id::text AS message_key, payload::text
                FROM recommendation_request_outbox
                WHERE published_at IS NULL
                ORDER BY created_at
                LIMIT 50
                """,
                (resultSet, rowNumber) -> new OutboxEvent(
                        resultSet.getString("event_id"),
                        resultSet.getString("message_key"),
                        resultSet.getString("payload")
                )
        );
        for (OutboxEvent event : events) {
            try {
                kafkaTemplate.send(recommendationRequestsTopic, event.messageKey(), event.payload())
                        .get(10, TimeUnit.SECONDS);
                jdbcTemplate.update(
                        "UPDATE recommendation_request_outbox SET published_at = now() WHERE event_id = ?::uuid",
                        event.eventId()
                );
                jdbcTemplate.update(
                        "UPDATE recommendation_requests SET status = 'PUBLISHED', updated_at = now() "
                                + "WHERE request_id = ?::uuid AND status = 'PENDING'",
                        event.messageKey()
                );
            } catch (Exception exception) {
                log.warn("Recommendation request publish will retry: eventId={}", event.eventId(), exception);
                return;
            }
        }
    }

    private record OutboxEvent(String eventId, String messageKey, String payload) {}
}
