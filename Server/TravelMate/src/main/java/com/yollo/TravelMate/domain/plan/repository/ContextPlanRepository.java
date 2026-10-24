package com.yollo.TravelMate.domain.plan.repository;

import java.util.List;
import java.util.stream.IntStream;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

@Repository
@RequiredArgsConstructor
public class ContextPlanRepository {
    private final PlanRepository planRepository;
    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public List<PlaceResult> requiredPlaces(List<Long> ids) {
        if (ids.isEmpty()) return List.of();
        String placeholders = String.join(",", java.util.Collections.nCopies(ids.size(), "?"));
        return jdbc.query("SELECT * FROM places WHERE id IN (" + placeholders + ")", (row, index) ->
                new PlaceResult(
                        row.getLong("id"), row.getString("name"), row.getString("description"),
                        row.getString("region"), row.getString("city"), row.getString("category"),
                        row.getString("source_category"), row.getObject("latitude", Double.class), row.getObject("longitude", Double.class),
                        0.0, row.getString("tour_content_id"), row.getString("image_url"), row.getString("homepage_url")
                ), ids.toArray());
    }

    @Transactional
    public long save(
            String userUid,
            GeneratePlanRequest request,
            GeneratedPlan generated,
            List<PlaceResult> candidates,
            String requestJson
    ) {
        long planId = planRepository.saveDraft(generated, candidates, userUid);
        jdbc.update("UPDATE plans SET context = (?::jsonb)->'context', request_payload = ?::jsonb WHERE plan_id = ?",
                requestJson, requestJson, planId);
        int defaultStay = request.context().preferences().pace() == PlanContext.Pace.RELAXED ? 60 : 40;
        jdbc.update("UPDATE pins SET stay_minutes = ? WHERE plan_id = ?", defaultStay, planId);
        request.requiredStops().forEach(stop -> jdbc.update(
                "UPDATE pins SET stay_minutes = ? WHERE plan_id = ? AND place_id = ?",
                stop.stayMinutes(), planId, stop.placeId()));
        return planId;
    }

    public PlanningResponse.Draft get(long planId, String userUid) {
        var headers = jdbc.query("SELECT title, context::text FROM plans WHERE plan_id = ? AND user_uid = ?",
                (row, index) -> new DraftHeader(row.getString("title"), readContext(row.getString("context"))),
                planId, userUid);
        if (headers.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        var pins = jdbc.query("""
                SELECT place_id, place_name, latitude, longitude, stay_minutes, sequence
                FROM pins WHERE plan_id = ? ORDER BY sequence
                """, (row, index) -> new PlanningResponse.Pin(
                        row.getLong("place_id"), row.getString("place_name"),
                        row.getDouble("latitude"), row.getDouble("longitude"),
                        row.getInt("stay_minutes"), row.getInt("sequence")
                ), planId);
        var header = headers.get(0);
        return new PlanningResponse.Draft(planId, header.context(), header.title(), pins, List.of(
                "운영시간과 실제 이동 경로가 검증되지 않은 초안입니다. 방문 시간과 동선은 확정되지 않았습니다."
        ));
    }

    private PlanContext readContext(String json) {
        try { return objectMapper.readValue(json, PlanContext.class); }
        catch (Exception exception) { throw new IllegalStateException("저장된 여행 조건을 읽지 못했습니다.", exception); }
    }
    private record DraftHeader(String title, PlanContext context) {}
}
