package com.yollo.TravelMate.domain.plan.repository;

import java.util.Optional;
import java.util.UUID;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@Repository
@RequiredArgsConstructor
public class PlanningJobRepository {
    public enum Operation { GENERATE, MANUAL }
    private final JdbcTemplate jdbc;

    public Optional<PlanningResponse.Job> findExisting(
            String userUid,
            Operation operation,
            UUID key,
            String requestJson
    ) {
        return jdbc.query("""
                SELECT *, request_payload = ?::jsonb AS same_request
                FROM planning_jobs WHERE user_uid = ? AND operation = ? AND idempotency_key = ?
                """, (row, index) -> {
            if (!row.getBoolean("same_request")) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "같은 요청 키에 다른 여행 조건을 보낼 수 없습니다.");
            }
            return toResponse(row);
        }, requestJson, userUid, operation.name(), key).stream().findFirst();
    }

    public boolean insert(
            UUID jobId,
            String userUid,
            Operation operation,
            UUID key,
            String requestJson
    ) {
        return jdbc.update("""
                INSERT INTO planning_jobs (job_id, user_uid, operation, idempotency_key, request_payload, status)
                VALUES (?, ?, ?, ?, ?::jsonb, 'QUEUED') ON CONFLICT DO NOTHING
                """, jobId, userUid, operation.name(), key, requestJson) == 1;
    }

    public PlanningResponse.Job get(UUID jobId, String userUid) {
        return jdbc.query(
                "SELECT * FROM planning_jobs WHERE job_id = ? AND user_uid = ?",
                (row, index) -> toResponse(row),
                jobId,
                userUid
        ).stream().findFirst().orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
    }

    public void update(UUID jobId, PlanningResponse.JobStatus status, Long planId, String error) {
        jdbc.update("UPDATE planning_jobs SET status = ?, plan_id = ?, error_message = ?, updated_at = now() WHERE job_id = ?",
                status.name(), planId, error, jobId);
    }

    public void failInterruptedJobs() {
        jdbc.update("""
                UPDATE planning_jobs SET status = 'FAILED',
                    error_message = '서버 재시작으로 중단되었습니다. 새 요청으로 다시 시도해 주세요.', updated_at = now()
                WHERE status IN ('QUEUED', 'RUNNING')
                """);
    }

    private static PlanningResponse.Job toResponse(java.sql.ResultSet row) throws java.sql.SQLException {
        UUID jobId = row.getObject("job_id", UUID.class);
        return new PlanningResponse.Job(
                jobId,
                PlanningResponse.JobStatus.valueOf(row.getString("status")),
                "/api/v1/planning-jobs/" + jobId,
                row.getObject("plan_id", Long.class),
                row.getString("error_message")
        );
    }
}
