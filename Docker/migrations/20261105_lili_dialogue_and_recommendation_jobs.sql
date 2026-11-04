-- LiLi presents drafts and recommendations as 2-4 visual-novel cuts; recommendations run as asynchronous jobs.
BEGIN;

ALTER TABLE plans ADD COLUMN IF NOT EXISTS character_dialogue JSONB;
-- 20261104 added a single emotion tag; the first cut's emotion replaces it before any release wrote drafts with it.
ALTER TABLE plans DROP COLUMN IF EXISTS character_emotion;

CREATE TABLE IF NOT EXISTS recommendation_jobs (
    job_id UUID PRIMARY KEY,
    user_uid VARCHAR(36) NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    idempotency_key UUID NOT NULL,
    request_payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL,
    result_payload JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_uid, idempotency_key)
);

COMMIT;
