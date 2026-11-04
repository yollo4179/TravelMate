-- One-off follow-up to 20261105_planning_job_user_facing_errors.sql; a fresh database has no jobs, so this is not an init script.
-- The first correction stored "the service is briefly not responding", a cause nobody verified, and LiLi read it
-- aloud as an outage. Model-call failures now state only that no draft was made. Drafts that could not be read or
-- cited evidence they were not given stored the parser's or citation check's wording; they now get the plain
-- reason the server stores for that case. Reasons from the draft rules (stay time, cafés, required stops) are
-- written for users and stay as they are.
-- Restoration evidence (job IDs and original text per database): docs/maintenance/planning-job-error-cleanup-20261105.md
UPDATE planning_jobs
SET error_message = '일정 초안을 만들지 못했어요. 같은 조건으로 다시 요청하거나 조건을 바꿔 요청해 주세요.'
WHERE status = 'FAILED'
  AND operation = 'GENERATE'
  AND (error_message = '일정 생성 서비스가 잠시 응답하지 않아요. 잠시 후 다시 요청해 주세요.'
       OR error_message LIKE 'LLM 호출 전 토큰 예산 검사 실패:%'
       OR error_message ~ '^[A-Za-z]')
RETURNING job_id;

-- Parser and citation-check wording observed in existing databases.
UPDATE planning_jobs
SET error_message = '만들어진 초안이 확인 단계를 통과하지 못해 저장하지 않았어요. 다시 요청해 주세요.'
WHERE status = 'FAILED'
  AND operation = 'GENERATE'
  AND error_message IN ('인용이 해당 장소에 실제 전달한 원문 근거에 속하지 않습니다.',
                        '인용에 출처 식별자가 없습니다.',
                        'AI 응답이 일정 JSON 형식과 일치하지 않습니다.',
                        'AI가 빈 결과를 반환했습니다.',
                        '만들어진 초안이 확인된 장소 정보와 맞지 않아 저장하지 않았어요. 다시 요청해 주세요.')
RETURNING job_id;
