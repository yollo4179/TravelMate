-- Character emotion chosen by the plan-generation model; NULL for older drafts or drafts written without a model call.
BEGIN;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS character_emotion VARCHAR(20);
COMMIT;
