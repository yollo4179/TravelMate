package com.yollo.TravelMate.domain.conversation.repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Optional;
import java.util.UUID;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.RecommendationJobResponse;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
@RequiredArgsConstructor
public class RecommendationJobRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    /** One job per user turn key; a retried turn returns the job it already queued. */
    public boolean insert(
            UUID jobId,
            String userUid,
            UUID turnKey,
            String requestJson
    ) {
        return jdbc.update("""
                INSERT INTO recommendation_jobs (job_id, user_uid, idempotency_key, request_payload, status)
                VALUES (?, ?, ?, ?::jsonb, ?) ON CONFLICT (user_uid, idempotency_key) DO NOTHING
                """, jobId, userUid, turnKey, requestJson, JobStatus.QUEUED.name()) == 1;
    }

    public Optional<RecommendationJobResponse> findByTurn(String userUid, UUID turnKey) {
        return jdbc.query(
                "SELECT * FROM recommendation_jobs WHERE user_uid = ? AND idempotency_key = ?",
                (row, index) -> toResponse(row),
                userUid,
                turnKey
        ).stream().findFirst();
    }

    public Optional<RecommendationJobResponse> get(UUID jobId, String userUid) {
        return jdbc.query(
                "SELECT * FROM recommendation_jobs WHERE job_id = ? AND user_uid = ?",
                (row, index) -> toResponse(row),
                jobId,
                userUid
        ).stream().findFirst();
    }

    public void update(
            UUID jobId,
            JobStatus status,
            String resultJson,
            String error
    ) {
        jdbc.update("""
                UPDATE recommendation_jobs
                SET status = ?, result_payload = COALESCE(?::jsonb, result_payload), error_message = ?, updated_at = now()
                WHERE job_id = ?
                """, status.name(), resultJson, error, jobId);
    }

    // A restart abandons in-memory workers, so unfinished jobs must not look as if they are still running.
    public void failInterruptedJobs() {
        jdbc.update("""
                UPDATE recommendation_jobs SET status = ?, error_message = ?, updated_at = now()
                WHERE status IN (?, ?)
                """, JobStatus.FAILED.name(), "서버가 다시 시작되어 추천 작업이 중단되었습니다.",
                JobStatus.QUEUED.name(), JobStatus.RUNNING.name());
    }

    private RecommendationJobResponse toResponse(ResultSet row) throws SQLException {
        UUID jobId = row.getObject("job_id", UUID.class);
        String result = row.getString("result_payload");
        return new RecommendationJobResponse(
                jobId,
                JobStatus.valueOf(row.getString("status")),
                RecommendationJobResponse.statusUrl(jobId),
                result == null ? null : readTree(result),
                row.getString("error_message")
        );
    }

    private JsonNode readTree(String json) {
        try {
            return mapper.readTree(json);
        } catch (Exception exception) {
            throw new IllegalStateException("저장된 추천 결과를 읽지 못했습니다.", exception);
        }
    }
}
