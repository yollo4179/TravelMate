package com.yollo.TravelMate.domain.plan.service;

import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.stream.IntStream;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.data.internal.PlanFailure;
import com.yollo.TravelMate.domain.plan.data.internal.PlanFailure.PlanFailureException;
import com.yollo.TravelMate.domain.plan.data.request.*;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.repository.*;
import com.yollo.TravelMate.domain.plan.validator.DraftPlanValidator;
import com.yollo.TravelMate.domain.plan.validator.PlanAreaValidator;
import com.yollo.TravelMate.domain.plan.validator.PlanEvidenceCitationValidator;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
@lombok.extern.slf4j.Slf4j
public class ContextPlanningService {
    private enum JobObservationOperation {
        IDEMPOTENCY_READ, INSERT_ACKNOWLEDGED, QUEUE_REJECTED, OWNER_SCOPED_READ, UPDATE_ACKNOWLEDGED
    }
    private final PlanningJobRepository jobs;
    private final ContextPlanRepository plans;
    private final PlaceSemanticSearchService searchService;
    private final ObjectMapper objectMapper;
    private final LlmClient llmClient;
    private final com.yollo.TravelMate.domain.plan.validator.ContextPlanResultValidator planValidator;
    private final com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory promptFactory;
    private final List<PlanFailureReaction> failureReactions;
    private final ExecutorService executor = new java.util.concurrent.ThreadPoolExecutor(
            2, 2, 0L, java.util.concurrent.TimeUnit.MILLISECONDS,
            new java.util.concurrent.ArrayBlockingQueue<>(10)
    );

    @PostConstruct
    void recover() { jobs.failInterruptedJobs(); }
    @PreDestroy
    void shutdown() { executor.shutdownNow(); }

    public PlanningResponse.Job generate(String userUid, UUID key, GeneratePlanRequest request) {
        validateRequest(request);
        String requestJson = encode(request);
        var previous = jobs.findExisting(userUid, PlanningJobRepository.Operation.GENERATE, key, requestJson);
        if (previous.isPresent()) {
            recordJob(previous.get().jobId(), previous.get().status(), previous.get().planId(), JobObservationOperation.IDEMPOTENCY_READ);
            return previous.get();
        }
        UUID jobId = UUID.randomUUID();
        if (!jobs.insert(jobId, userUid, PlanningJobRepository.Operation.GENERATE, key, requestJson)) {
            var existing = jobs.findExisting(userUid, PlanningJobRepository.Operation.GENERATE, key, requestJson).orElseThrow();
            recordJob(existing.jobId(), existing.status(), existing.planId(), JobObservationOperation.IDEMPOTENCY_READ);
            return existing;
        }
        recordJob(jobId, PlanningResponse.JobStatus.QUEUED, null, JobObservationOperation.INSERT_ACKNOWLEDGED);
        var generationContext = ObservationContext.child(ObservationContext.Phase.PLAN_GENERATION, jobId.toString(), null, null);
        try {
            executor.submit(() -> {
                try (var scope = ObservationContext.open(generationContext)) {
                    runGeneration(jobId, userUid, request, requestJson);
                }
            });
        } catch (java.util.concurrent.RejectedExecutionException exception) {
            fail(jobId, PlanFailure.QUEUE_FULL.classified(), request);
            recordJob(jobId, PlanningResponse.JobStatus.FAILED, null, JobObservationOperation.QUEUE_REJECTED);
        }
        return jobs.get(jobId, userUid);
    }

    public PlanningResponse.Draft create(String userUid, UUID key, GeneratePlanRequest request) {
        validateRequest(request);
        if (request.requiredStops().isEmpty()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "장소를 하나 이상 선택해 주세요.");
        String requestJson = encode(request);
        var existing = jobs.findExisting(userUid, PlanningJobRepository.Operation.MANUAL, key, requestJson);
        if (existing.isPresent()) {
            if (existing.get().planId() == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "이미 처리 중이거나 실패한 요청입니다. 조건을 확인해 주세요.");
            return plans.get(existing.get().planId(), userUid);
        }
        validateHoursPolicy(request);
        var candidates = validatedRequiredPlaces(request);
        UUID jobId = UUID.randomUUID();
        if (!jobs.insert(jobId, userUid, PlanningJobRepository.Operation.MANUAL, key, requestJson)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "이미 처리 중인 요청입니다.");
        }
        try {
            var generated = new GeneratedPlan("나의 여행 일정", request.context().additionalRequest(),
                    IntStream.range(0, request.requiredStops().size()).mapToObj(index ->
                            new GeneratedPlan.GeneratedPin(request.requiredStops().get(index).placeId(), index + 1, "직접 선택", "필수 방문 장소")
                    ).toList());
            var validated = DraftPlanValidator.validate(generated, candidates, request);
            long planId = plans.save(userUid, request, validated, candidates, requestJson);
            jobs.update(jobId, PlanningResponse.JobStatus.SUCCEEDED, planId, null);
            return plans.get(planId, userUid);
        } catch (RuntimeException exception) {
            String message = exception instanceof ResponseStatusException status
                    ? status.getReason() : "초안 저장에 실패했습니다.";
            jobs.update(jobId, PlanningResponse.JobStatus.FAILED, null, message);
            throw exception;
        }
    }

    public PlanningResponse.Job job(UUID jobId, String userUid) {
        var job = jobs.get(jobId, userUid);
        recordJob(jobId, job.status(), job.planId(), JobObservationOperation.OWNER_SCOPED_READ);
        return job;
    }
    public PlanningResponse.Draft plan(long planId, String userUid) { return plans.get(planId, userUid); }

    public List<com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult> search(
            PlanContext context,
            String query,
            int limit
    ) {
        return search(context, query, limit, com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService.RankingMode.RERANKED);
    }

    public List<com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult> search(
            PlanContext context,
            String query,
            int limit,
            com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService.RankingMode rankingMode
    ) {
        validateArea(context);
        String intent = query + " " + String.join(" ", context.preferences().themes())
                + " " + Objects.toString(context.additionalRequest(), "");
        return searchService.search(intent.trim(), null, null, null, limit, context.area(), rankingMode);
    }

    public static void validateArea(PlanContext context) {
        if (context.area().type() != PlanContext.AreaType.CIRCLE) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "지역 사전 검색은 아직 지원하지 않습니다. 지도에서 범위를 선택해 주세요.");
        }
    }

    private void validateRequest(GeneratePlanRequest request) {
        validateArea(request.context());
        if (request.context().transportMode() != PlanContext.TransportMode.WALK) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "현재는 도보 여행만 지원합니다.");
        }
        long distinctCount = request.requiredStops().stream().map(GeneratePlanRequest.RequiredStop::placeId).distinct().count();
        if (distinctCount != request.requiredStops().size()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "필수 장소가 중복되었습니다.");
        if (request.requiredStops().stream().anyMatch(stop -> stop.fixedStartAt() != null)) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "고정 방문 시간은 경로 검증 연결 후 지원됩니다.");
        }
        if (request.context().preferences().budgetKrw() != null) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "방문 비용을 확인할 수 없어 예산 제한을 검증할 수 없습니다.");
        }
    }

    private void validateHoursPolicy(GeneratePlanRequest request) {
        if (request.context().unknownHoursPolicy() == PlanContext.UnknownHoursPolicy.EXCLUDE) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "현재 장소의 운영시간을 검증할 수 없습니다. 미확인 장소 포함을 선택하면 확인이 필요한 초안으로 저장할 수 있습니다.");
        }
    }

    private List<PlaceResult> validatedRequiredPlaces(GeneratePlanRequest request) {
        var places = plans.requiredPlaces(request.requiredStops().stream().map(GeneratePlanRequest.RequiredStop::placeId).toList());
        if (places.size() != request.requiredStops().size()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "존재하지 않는 필수 장소가 있습니다.");
        var area = request.context().area();
        if (places.stream().anyMatch(place -> !PlanAreaValidator.contains(area, place))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "필수 장소가 선택한 여행 범위를 벗어납니다.");
        }
        return places;
    }

    private void runGeneration(UUID jobId, String userUid, GeneratePlanRequest request, String requestJson) {
        try (var scope = ObservationContext.open(ObservationContext.child(
                ObservationContext.Phase.PLAN_GENERATION, jobId.toString(), null, null))) {
            generateDraft(jobId, userUid, request, requestJson);
        }
    }

    private void generateDraft(UUID jobId, String userUid, GeneratePlanRequest request, String requestJson) {
        // Kept outside the try so a rejected draft is recorded with the exact output and candidates it was judged on.
        var attempt = new DraftAttempt();
        try {
            jobs.update(jobId, PlanningResponse.JobStatus.RUNNING, null, null);
            recordJob(jobId, PlanningResponse.JobStatus.RUNNING, null, JobObservationOperation.UPDATE_ACKNOWLEDGED);
            validateHoursPolicy(request);
            var required = validatedRequiredPlaces(request);
            log.info("planning job={} stage=SEARCHING radiusMeters={}", jobId, request.context().area().radiusMeters());
            String query = String.join(" ", request.context().preferences().themes()) + " "
                    + Objects.toString(request.context().additionalRequest(), "");
            // LiLi's query states what the user asked for in this turn, so it leads the candidate search.
            if (request.searchQuery() != null && !request.searchQuery().isBlank()) query = request.searchQuery() + " " + query;
            if (query.isBlank()) query = "여행 관광 산책";
            attempt.query = query;
            var candidatesById = new LinkedHashMap<Long, PlaceResult>();
            var searchResults = searchService.search(
                    query,
                    null,
                    null,
                    null,
                    10 - required.size(),
                    request.context().area()
            );
            searchResults.forEach(result -> candidatesById.put(result.place().id(), result.place()));
            required.forEach(place -> candidatesById.put(place.id(), place));
            var candidates = List.copyOf(candidatesById.values());
            attempt.candidateIds = List.copyOf(candidatesById.keySet());
            if (candidates.isEmpty()) throw new PlanFailureException(PlanFailure.NO_CANDIDATES_IN_AREA);
            var preparedPrompt = promptFactory.prepare(request, candidates, searchResults);
            String prompt = preparedPrompt.userPrompt();
            attempt.prompt = prompt;
            log.info("planning job={} stage=GENERATING candidateIds={} contextIncluded=true promptCharacters={}",
                    jobId, candidatesById.keySet(), prompt.length());
            String output;
            try {
                output = llmClient.generate(promptFactory.systemPrompt(), prompt);
            } catch (RuntimeException exception) {
                throw new PlanFailureException(PlanFailure.GENERATION_UNAVAILABLE, exception);
            }
            attempt.output = output;
            log.info("planning job={} stage=VALIDATING_RESULT responseCharacters={}", jobId, output == null ? 0 : output.length());
            var generated = validatedDraft(output, candidates, request, preparedPrompt, attempt);
            var normalized = new GeneratedPlan(
                    generated.planTitle(),
                    generated.planDescription(),
                    IntStream.range(0, generated.pins().size()).mapToObj(index -> {
                        var pin = generated.pins().get(index);
                        return new GeneratedPlan.GeneratedPin(pin.placeId(), index + 1, pin.activity(), pin.reason());
                    }).toList(),
                    generated.dialogue()
            );
            long planId = plans.save(userUid, request, normalized, candidates, requestJson);
            // Recorded before the status flips, as on failure, so whoever sees SUCCEEDED can already read the draft record.
            recordDraft(attempt, PlanningResponse.JobStatus.SUCCEEDED, null);
            jobs.update(jobId, PlanningResponse.JobStatus.SUCCEEDED, planId, null);
            recordJob(jobId, PlanningResponse.JobStatus.SUCCEEDED, planId, JobObservationOperation.UPDATE_ACKNOWLEDGED);
            log.info("planning job={} stage=SUCCEEDED planId={} pinCount={}", jobId, planId, normalized.pins().size());
        } catch (Exception exception) {
            log.warn("planning job={} stage=FAILED exception={}", jobId, exception.toString());
            // What the model call or its draft raised stays internal; the kind decides what users are told and how LiLi reacts.
            var failure = PlanFailure.classify(exception);
            recordDraft(attempt, PlanningResponse.JobStatus.FAILED, exception);
            fail(jobId, failure, request);
            recordJob(jobId, PlanningResponse.JobStatus.FAILED, null, JobObservationOperation.UPDATE_ACKNOWLEDGED);
        }
    }

    private GeneratedPlan validatedDraft(
            String output,
            List<PlaceResult> candidates,
            GeneratePlanRequest request,
            com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.PreparedPrompt preparedPrompt,
            DraftAttempt attempt
    ) {
        try {
            var generated = DraftPlanValidator.validate(planValidator.parse(output), candidates, request);
            // A citation that fails verification is removed and recorded; the rest of the draft is still saved.
            var review = PlanEvidenceCitationValidator.review(generated, preparedPrompt);
            attempt.droppedCitations = review.dropped();
            return review.plan();
        } catch (ResponseStatusException conditionReason) {
            // The draft rules word their reasons for users (they also guard manual plans), e.g. a café the area lacks.
            throw conditionReason;
        } catch (RuntimeException exception) {
            throw new PlanFailureException(PlanFailure.DRAFT_REJECTED, exception);
        }
    }

    private void recordDraft(DraftAttempt attempt, PlanningResponse.JobStatus status, Exception rejected) {
        Throwable failure = rejected instanceof PlanFailureException wrapped && wrapped.getCause() != null ? wrapped.getCause() : rejected;
        var event = objectMapper.createObjectNode().put("status", status.name()).put("query", attempt.query)
                .put("prompt", attempt.prompt)
                .put("systemPromptSha256", com.yollo.TravelMate.ai.llm.budget.LlmCallGuard.sha256(promptFactory.systemPrompt()))
                .put("output", attempt.output)
                .put("failureKind", rejected == null ? null : PlanFailure.classify(rejected).kind().name())
                .put("failureType", failure == null ? null : failure.getClass().getSimpleName())
                .put("failureMessage", failure == null ? null : failure instanceof ResponseStatusException statusFailure
                        ? statusFailure.getReason() : failure.getMessage());
        var candidates = event.putArray("candidateIds");
        attempt.candidateIds.forEach(candidates::add);
        var dropped = event.putArray("droppedCitations");
        attempt.droppedCitations.forEach(item -> dropped.addObject().put("placeId", item.placeId())
                .put("evidenceId", item.citation().evidenceId()).put("sourceId", item.citation().sourceId())
                .put("quote", item.citation().quote()).put("reason", item.reason().name()));
        ObservationContext.record(ObservationContext.Event.PLAN_DRAFT, event);
    }

    /**
     * LiLi's reaction is stored with the error before the job turns FAILED, so whoever sees the failure can read it.
     * A reaction that cannot be made leaves only the error text; the job must still leave RUNNING.
     */
    private void fail(
            UUID jobId,
            PlanFailure.Classified failure,
            GeneratePlanRequest request
    ) {
        List<com.yollo.TravelMate.domain.conversation.data.DialogueCut> dialogue = null;
        try {
            dialogue = com.yollo.TravelMate.domain.conversation.pipeline.ModuleSelection.requireOne(
                    failureReactions,
                    reaction -> reaction.supports(failure.kind().reaction()),
                    "plan failure reaction"
            ).execute(failure, request);
        } catch (RuntimeException exception) {
            log.warn("planning job={} reaction unavailable kind={} exception={}", jobId, failure.kind(), exception.toString());
        }
        jobs.fail(jobId, failure.userMessage(), dialogue);
    }

    /** What one generation attempt saw and produced, filled in as the job advances. */
    private static final class DraftAttempt {
        private String query;
        private List<Long> candidateIds = List.of();
        private String prompt;
        private String output;
        private List<PlanEvidenceCitationValidator.Dropped> droppedCitations = List.of();
    }

    private void recordJob(
            UUID jobId,
            PlanningResponse.JobStatus status,
            Long planId,
            JobObservationOperation operation
    ) {
        try (var scope = ObservationContext.open(ObservationContext.child(
                ObservationContext.Phase.PLAN_GENERATION, jobId.toString(), null, null))) {
            var snapshot = objectMapper.createObjectNode().put("jobId", jobId.toString())
                    .put("status", status.name()).put("planId", planId).put("operation", operation.name());
            ObservationContext.record(ObservationContext.Event.JOB_STATUS, snapshot);
        }
    }

    private String encode(GeneratePlanRequest request) {
        try { return objectMapper.writeValueAsString(request); }
        catch (JsonProcessingException exception) { throw new IllegalStateException("여행 조건 직렬화 실패", exception); }
    }

}
