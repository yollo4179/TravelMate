package com.yollo.TravelMate.domain.pin.repository;

import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import com.yollo.TravelMate.domain.pin.data.internal.GeneratedPinActivities;

@Repository
public class PinActivityRepository {

    private final JdbcTemplate jdbc;

    public PinActivityRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * 극소 계획을 SUGGESTED 상태로 저장
     * 확정된 정책: 기존 SUGGESTED만 지우고 새로 채움 (CONFIRMED는 보존).
     * "다시 추천받기"를 눌러도 사용자가 이미 확정한 CONFIRMED는 유지됩니다.
     */
    @Transactional
    public void saveSuggested(GeneratedPinActivities plan) {
    	String updateSql = """
    		    delete from pin_activities 
    		    where 1 = 1
    		      and pin_id = ? 
    		      and status = 'SUGGESTED'
    		    """;
    	
        jdbc.update(
        		updateSql,
                plan.pinId());

        List<GeneratedPinActivities.GeneratedActivity> activities = plan.activities();
        String sql = """
                insert into pin_activities (pin_id, sequence, activity, reason, estimated_minutes, status)
                values (?, ?, ?, ?, ?, 'SUGGESTED')
                """;

        jdbc.batchUpdate(sql, activities, activities.size(), (ps, item) -> {
            ps.setLong(1, plan.pinId());
            ps.setInt(2, item.sequence());
            ps.setString(3, item.activity());
            ps.setString(4, item.reason());
            ps.setObject(5, item.estimatedMinutes()); // null 허용
        });
    }

    /** 사용자가 확정 시 SUGGESTED → CONFIRMED */
    public void confirmSuggested(Long pinId) {
        
    	String sql = """ 
    			update pin_activities 
    			set status = 'CONFIRMED' 
    			where 1 = 1
    			and pin_id = ? 
    			and status = 'SUGGESTED'
    			""";
    	jdbc.update(
    			sql,
                pinId);
    }
}