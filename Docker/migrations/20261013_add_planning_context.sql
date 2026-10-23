BEGIN;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS context JSONB;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS request_payload JSONB;
ALTER TABLE pins ADD COLUMN IF NOT EXISTS stay_minutes INTEGER;
CREATE TABLE IF NOT EXISTS planning_jobs (
    job_id UUID PRIMARY KEY,
    user_uid VARCHAR(36) NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    idempotency_key UUID NOT NULL,
    operation VARCHAR(20) NOT NULL,
    request_payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL,
    plan_id BIGINT REFERENCES plans(plan_id) ON DELETE SET NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_uid, operation, idempotency_key)
);
COMMIT;
