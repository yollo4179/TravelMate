package com.yollo.TravelMate.domain.plan.repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
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
    private static final TypeReference<List<DialogueCut>> CUTS = new TypeReference<>() {};
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

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

    /** The error text stays for clients and operators; LiLi's reaction is what the user is shown in her voice. */
    public void fail(
            UUID jobId,
            String error,
            List<DialogueCut> dialogue
    ) {
        jdbc.update("""
                UPDATE planning_jobs SET status = 'FAILED', plan_id = NULL, error_message = ?,
                    failure_dialogue = ?::jsonb, updated_at = now()
                WHERE job_id = ?
                """, error, encode(dialogue), jobId);
    }

    public void failInterruptedJobs() {
        jdbc.update("""
                UPDATE planning_jobs SET status = 'FAILED',
                    error_message = '서버 재시작으로 중단되었습니다. 새 요청으로 다시 시도해 주세요.', updated_at = now()
                WHERE status IN ('QUEUED', 'RUNNING')
                """);
    }

    private PlanningResponse.Job toResponse(java.sql.ResultSet row) throws java.sql.SQLException {
        UUID jobId = row.getObject("job_id", UUID.class);
        return new PlanningResponse.Job(
                jobId,
                PlanningResponse.JobStatus.valueOf(row.getString("status")),
                "/api/v1/planning-jobs/" + jobId,
                row.getObject("plan_id", Long.class),
                row.getString("error_message"),
                decode(row.getString("failure_dialogue"))
        );
    }

    private String encode(List<DialogueCut> dialogue) {
        try {
            return mapper.writeValueAsString(dialogue);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("LiLi reaction could not be stored", exception);
        }
    }

    private List<DialogueCut> decode(String stored) {
        if (stored == null) return null;
        try {
            return mapper.readValue(stored, CUTS);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored LiLi reaction is unreadable", exception);
        }
    }
}
