-- LiLi's reaction to a failed draft job is stored beside the error text, so users hear her voice instead of the
-- server's message. Nullable: jobs that failed before this column, or whose reaction could not be made, keep only the error.
BEGIN;

ALTER TABLE planning_jobs ADD COLUMN IF NOT EXISTS failure_dialogue JSONB;

COMMIT;
