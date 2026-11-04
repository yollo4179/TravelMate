package com.yollo.TravelMate.domain.plan.repository;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Repository
@RequiredArgsConstructor
public class PlanRepository {

    // Plain records and enums only, so the default mapper serializes the dialogue the same everywhere.
    private static final ObjectMapper JSON = new ObjectMapper();
    private final JdbcTemplate jdbc;

    @Transactional
    public Long saveDraft(GeneratedPlan plan, List<PlaceResult> candidates, String userUid) {
        // 후보를 id로 조회 가능하게 (name·좌표를 DB값으로 채우기 위함)
        Map<Long, PlaceResult> byId = candidates.stream()
                .collect(Collectors.toMap(PlaceResult::id, p -> p));

        
        Long planId = insertPlan(userUid, plan);

        // 2) pins 저장 — placeId만 신뢰
        for (GeneratedPlan.GeneratedPin pin : plan.pins()) {
            PlaceResult place = byId.get(pin.placeId());  // Validator가 이미 검증했으니 non-null
            String memo = pin.activity() + " - " + pin.reason();

            jdbc.update("""
                    INSERT INTO pins (plan_id, place_id, place_name, latitude, longitude, memo, sequence)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    planId,
                    place.id(),           // place_id FK
                    place.name(),         // 이름은 DB에서 (LLM 창작 아님)
                    place.latitude(),     // 좌표도 DB에서
                    place.longitude(),
                    memo,
                    pin.sequence());
        }
        return planId;
    }

    private Long insertPlan(String userUid, GeneratedPlan plan) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(conn -> {
            PreparedStatement ps = conn.prepareStatement("""
                    INSERT INTO plans (user_uid, title, description, status, character_dialogue)
                    VALUES (?, ?, ?, 'DRAFT', ?::jsonb)
                    """, new String[]{"plan_id"});
            ps.setString(1, userUid);
            ps.setString(2, plan.planTitle());
            ps.setString(3, plan.planDescription());
            // Every plan path saves drafts here, so LiLi's cuts are stored once instead of per caller.
            ps.setString(4, dialogueJson(plan));
            return ps;
        }, keyHolder);
        return keyHolder.getKey().longValue();
    }

    private static String dialogueJson(GeneratedPlan plan) {
        if (plan.dialogue() == null || plan.dialogue().isEmpty()) return null;
        try {
            return JSON.writeValueAsString(plan.dialogue());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("초안 대사를 저장 형식으로 바꾸지 못했습니다.", exception);
        }
    }
}