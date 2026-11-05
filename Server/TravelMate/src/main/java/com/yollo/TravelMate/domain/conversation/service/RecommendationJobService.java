package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import com.yollo.TravelMate.ai.llm.budget.TokenBudgetException;
import com.yollo.TravelMate.ai.llm.observation.ObservationContext;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.data.RecommendationJobResponse;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliPrompts;
import com.yollo.TravelMate.domain.conversation.repository.RecommendationJobRepository;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;
import com.yollo.TravelMate.domain.place.service.PlaceCoverageService;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/** Search with LiLi's query, then let LiLi explain the grounded candidates in 2-4 cuts, outside the chat turn. */
@Service
@RequiredArgsConstructor
public class RecommendationJobService {
    private static final int WORKERS = 2;
    private static final int QUEUE_CAPACITY = 10;
    private final RecommendationJobRepository jobs;
    private final ConversationEvidencePreparation evidence;
    private final ConversationToolRegistry registry;
    private final LiliTurns lili;
    private final ConversationAnswerRenderer renderer;
    private final ObjectMapper mapper;
    private final PlaceCoverageService coverage;
    private final ExecutorService executor = new ThreadPoolExecutor(
            WORKERS,
            WORKERS,
            0L,
            TimeUnit.MILLISECONDS,
            new ArrayBlockingQueue<>(QUEUE_CAPACITY)
    );

    @PostConstruct
    void recover() {
        jobs.failInterruptedJobs();
    }

    @PreDestroy
    void shutdown() {
        executor.shutdownNow();
    }

    public ConversationTool.Result submit(
            String userUid,
            UUID turnKey,
            ConversationRequest request,
            String query
    ) {
        UUID jobId = UUID.randomUUID();
        var payload = mapper.createObjectNode().put("query", query).put("message", request.message());
        payload.set("searchContext", mapper.valueToTree(request.searchContext()));
        if (!jobs.insert(jobId, userUid, turnKey, payload.toString())) {
            return result(jobs.findByTurn(userUid, turnKey).orElseThrow());
        }
        var context = ObservationContext.child(ObservationContext.Phase.RECOMMENDATION_GENERATION, jobId.toString(), null, null);
        try {
            executor.submit(() -> {
                try (var scope = ObservationContext.open(context)) {
                    run(jobId, userUid, turnKey, request, query);
                }
            });
        } catch (RejectedExecutionException exception) {
            jobs.update(jobId, JobStatus.FAILED, null, "추천 요청이 많습니다. 잠시 후 다시 요청해 주세요.");
        }
        return result(jobs.get(jobId, userUid).orElseThrow());
    }

    public RecommendationJobResponse get(UUID jobId, String userUid) {
        return jobs.get(jobId, userUid).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
    }

    private void run(
            UUID jobId,
            String userUid,
            UUID turnKey,
            ConversationRequest request,
            String query
    ) {
        try {
            jobs.update(jobId, JobStatus.RUNNING, null, null);
            long started = System.nanoTime();
            var prepared = evidence.prepare(userUid, turnKey, request.withMessage(query), registry);
            var event = mapper.createObjectNode().put("state", prepared.state().name()).put("query", query)
                    .put("sourceTool", prepared.source() == null ? null : prepared.source().wireName())
                    .put("durationMs", (System.nanoTime() - started) / 1_000_000.0);
            if (prepared.result() != null) {
                event.set("modelData", prepared.result().modelData());
                event.set("publicData", prepared.result().publicData());
            }
            ObservationContext.record(ObservationContext.Event.EVIDENCE_PREPARATION, event);
            var response = answer(request, query, prepared);
            jobs.update(jobId, JobStatus.SUCCEEDED, mapper.writeValueAsString(response), null);
        } catch (Exception exception) {
            jobs.update(jobId, JobStatus.FAILED, null, "추천 결과를 만들지 못했습니다.");
        }
    }

    private ConversationResponse answer(
            ConversationRequest request,
            String query,
            ConversationEvidencePreparation.Prepared prepared
    ) {
        var input = mapper.createObjectNode().put("message", request.message()).put("searchQuery", query);
        input.set("searchContext", mapper.valueToTree(request.searchContext()));
        var serverEvidence = input.putObject("serverEvidence").put("state", prepared.state().name());
        input.set("executionFacts", mapper.valueToTree(RecommendationExecutionFacts.execute(request, prepared)));
        // Without it LiLi told users to switch the search to areas the data does not hold.
        var covered = coverage.current();
        if (covered.known()) input.set("searchCoverage", mapper.valueToTree(covered.facts()));
        if (prepared.result() != null) serverEvidence.set("data", LiliEvidenceView.of(prepared.result().modelData()));
        long started = System.nanoTime();
        final LlmTurn completion;
        try {
            completion = lili.call(LiliPrompts.Prompt.RECOMMENDATION, request, input,
                    LiliTurnContract.RECOMMENDATION_NAME, LiliTurnContract.recommendationSchema());
        } catch (RuntimeException exception) {
            lili.record(LiliTurns.Stage.RECOMMENDATION, LiliPrompts.Prompt.RECOMMENDATION, null, elapsed(started));
            return renderer.liliFallback(prepared.result(), termination(exception), 1, List.of());
        }
        lili.record(LiliTurns.Stage.RECOMMENDATION, LiliPrompts.Prompt.RECOMMENDATION, completion, elapsed(started));
        try {
            var sources = prepared.result() == null ? Map.<String, com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory.CitationSource>of()
                    : prepared.result().sources();
            var recommendation = lili.recommendation(completion.content(), sources);
            return renderer.dialogue(prepared.result(), recommendation.intent(), recommendation.citations(),
                    recommendation.dialogue(), List.of(), Termination.COMPLETED, 1, List.of());
        } catch (Exception exception) {
            // Keep the strict citation rule; the verified cards still reach the user with a fallback line.
            return renderer.liliFallback(prepared.result(), Termination.INVALID_RESPONSE, 1, List.of());
        }
    }

    private ConversationTool.Result result(RecommendationJobResponse job) {
        var data = mapper.createObjectNode().put("jobId", job.jobId().toString()).put("status", job.status().name())
                .put("statusUrl", job.statusUrl());
        return ConversationTool.Result.builder().type(ResultType.RECOMMENDATION_JOB).publicData(data).modelData(data).build();
    }

    static Termination termination(RuntimeException exception) {
        if (!(exception instanceof TokenBudgetException budget)) return Termination.MODEL_FAILED;
        return budget.reason() == TokenBudgetException.Reason.COUNT_UNAVAILABLE ? Termination.COUNT_UNAVAILABLE : Termination.BUDGET_REJECTED;
    }

    private static double elapsed(long started) {
        return (System.nanoTime() - started) / 1_000_000.0;
    }
}
