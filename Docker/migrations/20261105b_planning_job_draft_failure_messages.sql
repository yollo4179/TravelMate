-- One-off follow-up to 20261105_planning_job_user_facing_errors.sql; a fresh database has no jobs, so this is not an init script.
-- The first correction stored "the service is briefly not responding", a cause nobody verified, and LiLi read it
-- aloud as an outage. Model-call failures now state only that no draft was made. Drafts the server's own checks
-- rejected stored the validator's wording; they now get the plain reason the server stores for that case.
-- Restoration evidence (job IDs and original text per database): docs/maintenance/planning-job-error-cleanup-20261105.md
UPDATE planning_jobs
SET error_message = '일정 초안을 만들지 못했어요. 같은 조건으로 다시 요청하거나 조건을 바꿔 요청해 주세요.'
WHERE status = 'FAILED'
  AND operation = 'GENERATE'
  AND (error_message = '일정 생성 서비스가 잠시 응답하지 않아요. 잠시 후 다시 요청해 주세요.'
       OR error_message LIKE 'LLM 호출 전 토큰 예산 검사 실패:%'
       OR error_message ~ '^[A-Za-z]')
RETURNING job_id;

-- Validator wording observed in existing databases; each one means the model's draft, not the user's request, failed a check.
UPDATE planning_jobs
SET error_message = '만들어진 초안이 확인된 장소 정보와 맞지 않아 저장하지 않았어요. 다시 요청해 주세요.'
WHERE status = 'FAILED'
  AND operation = 'GENERATE'
  AND error_message IN ('인용이 해당 장소에 실제 전달한 원문 근거에 속하지 않습니다.',
                        '방문 체류시간이 여행 가능 시간을 초과합니다.')
RETURNING job_id;
