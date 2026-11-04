-- One-off data correction for existing databases; a fresh database has no jobs, so this is not an init script.
-- Jobs that failed before the server separated user-facing reasons from model-call failures stored the
-- internal cause (token budget guard, provider/budget errors in English). That text is shown to users and
-- read aloud by LiLi, so it is replaced with the notice the server now stores for the same failures.
-- Restoration evidence (job IDs and original text per database): docs/maintenance/planning-job-error-cleanup-20261105.md
UPDATE planning_jobs
SET error_message = '일정 생성 서비스가 잠시 응답하지 않아요. 잠시 후 다시 요청해 주세요.'
WHERE status = 'FAILED'
  AND (error_message LIKE 'LLM 호출 전 토큰 예산 검사 실패:%'
       OR error_message ~ '^[A-Za-z]')
RETURNING job_id;
