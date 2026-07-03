package com.yollo.TravelMate.domain.plan.repository;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
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

    private final JdbcTemplate jdbc;

    @Transactional
    public Long saveDraft(GeneratedPlan plan, List<PlaceResult> candidates, String userUid) {
        // 후보를 id로 조회 가능하게 (name·좌표를 DB값으로 채우기 위함)
        Map<Long, PlaceResult> byId = candidates.stream()
                .collect(Collectors.toMap(PlaceResult::id, p -> p));

        
        Long planId = insertPlan(userUid, plan.planTitle(), plan.planDescription());

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

    private Long insertPlan(String userUid, String title, String description) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(conn -> {
            PreparedStatement ps = conn.prepareStatement("""
                    INSERT INTO plans (user_uid, title, description, status)
                    VALUES (?, ?, ?, 'DRAFT')
                    """, new String[]{"plan_id"});
            ps.setString(1, userUid);
            ps.setString(2, title);
            ps.setString(3, description);
            return ps;
        }, keyHolder);
        return keyHolder.getKey().longValue();
    }
}