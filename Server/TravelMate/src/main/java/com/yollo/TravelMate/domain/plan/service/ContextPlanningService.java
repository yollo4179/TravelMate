package com.yollo.TravelMate.domain.plan.service;

import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.stream.Collectors;
import java.util.stream.IntStream;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.place.formatter.CandidateFormatter;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.data.request.*;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.prompts.PlanPrompts;
import com.yollo.TravelMate.domain.plan.repository.*;
import com.yollo.TravelMate.domain.plan.validator.PlanValidator;
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
    private final PlanningJobRepository jobs;
    private final ContextPlanRepository plans;
    private final PlaceSemanticSearchService searchService;
    private final ObjectMapper objectMapper;
    private final LlmClient llmClient;
    private final com.yollo.TravelMate.domain.plan.validator.ContextPlanResultValidator planValidator;
    private final com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory promptFactory;
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
        if (previous.isPresent()) return previous.get();
        UUID jobId = UUID.randomUUID();
        if (!jobs.insert(jobId, userUid, PlanningJobRepository.Operation.GENERATE, key, requestJson)) {
            return jobs.findExisting(userUid, PlanningJobRepository.Operation.GENERATE, key, requestJson).orElseThrow();
        }
        try {
            executor.submit(() -> runGeneration(jobId, userUid, request, requestJson));
        } catch (java.util.concurrent.RejectedExecutionException exception) {
            jobs.update(jobId, PlanningResponse.JobStatus.FAILED, null, "생성 요청이 많습니다. 잠시 후 새 요청으로 시도해 주세요.");
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
        var candidates = validatedRequiredPlaces(request);
        validateHoursPolicy(request);
        UUID jobId = UUID.randomUUID();
        if (!jobs.insert(jobId, userUid, PlanningJobRepository.Operation.MANUAL, key, requestJson)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "이미 처리 중인 요청입니다.");
        }
        try {
            var generated = new GeneratedPlan("나의 여행 일정", request.context().additionalRequest(),
                    IntStream.range(0, request.requiredStops().size()).mapToObj(index ->
                            new GeneratedPlan.GeneratedPin(request.requiredStops().get(index).placeId(), index + 1, "직접 선택", "필수 방문 장소")
                    ).toList());
            long planId = plans.save(userUid, request, generated, candidates, requestJson);
            jobs.update(jobId, PlanningResponse.JobStatus.SUCCEEDED, planId, null);
            return plans.get(planId, userUid);
        } catch (RuntimeException exception) {
            jobs.update(jobId, PlanningResponse.JobStatus.FAILED, null, "초안 저장에 실패했습니다.");
            throw exception;
        }
    }

    public PlanningResponse.Job job(UUID jobId, String userUid) { return jobs.get(jobId, userUid); }
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
        if (places.stream().anyMatch(place -> distanceMeters(area.center(), place) > area.radiusMeters())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "필수 장소가 선택한 여행 범위를 벗어납니다.");
        }
        return places;
    }

    private void runGeneration(UUID jobId, String userUid, GeneratePlanRequest request, String requestJson) {
        try {
            jobs.update(jobId, PlanningResponse.JobStatus.RUNNING, null, null);
            validateHoursPolicy(request);
            var required = validatedRequiredPlaces(request);
            log.info("planning job={} stage=SEARCHING radiusMeters={}", jobId, request.context().area().radiusMeters());
            String query = String.join(" ", request.context().preferences().themes()) + " "
                    + Objects.toString(request.context().additionalRequest(), "");
            if (query.isBlank()) query = "여행 관광 산책";
            var candidatesById = new LinkedHashMap<Long, PlaceResult>();
            searchService.search(query, null, null, null, 10 - required.size(), request.context().area())
                    .forEach(result -> candidatesById.put(result.place().id(), result.place()));
            required.forEach(place -> candidatesById.put(place.id(), place));
            var candidates = List.copyOf(candidatesById.values());
            if (candidates.isEmpty()) throw new IllegalStateException("선택한 여행 범위에서 장소를 찾지 못했습니다.");
            String prompt = promptFactory.create(request, candidates);
            log.info("planning job={} stage=GENERATING candidateIds={} contextIncluded=true promptCharacters={}",
                    jobId, candidatesById.keySet(), prompt.length());
            String output = llmClient.generate(PlanPrompts.PLANNER_SYSTEM, prompt);
            log.info("planning job={} stage=VALIDATING_RESULT responseCharacters={}", jobId, output == null ? 0 : output.length());
            var generated = planValidator.validate(output, candidatesById.keySet(), request);
            var selectedIds = generated.pins().stream().map(GeneratedPlan.GeneratedPin::placeId).collect(Collectors.toSet());
            if (selectedIds.size() != generated.pins().size()) throw new IllegalStateException("생성 결과에 중복 장소가 있어 저장하지 않았습니다.");
            if (!selectedIds.containsAll(required.stream().map(PlaceResult::id).toList())) throw new IllegalStateException("생성 결과에서 필수 장소가 누락되어 저장하지 않았습니다.");
            for (var requirement : request.context().categoryRequirements()) {
                long cafeCount = selectedIds.stream().map(candidatesById::get)
                        .filter(place -> "카페".equals(place.category()) || "카페".equals(place.sourceCategory())).count();
                if (requirement.category() == PlanContext.Category.CAFE && cafeCount < requirement.minCount()) {
                    throw new IllegalStateException("선택한 범위에서 필수 카페 조건을 충족하지 못했습니다.");
                }
            }
            var normalized = new GeneratedPlan(generated.planTitle(), generated.planDescription(),
                    IntStream.range(0, generated.pins().size()).mapToObj(index -> {
                        var pin = generated.pins().get(index);
                        return new GeneratedPlan.GeneratedPin(pin.placeId(), index + 1, pin.activity(), pin.reason());
                    }).toList());
            long planId = plans.save(userUid, request, normalized, candidates, requestJson);
            jobs.update(jobId, PlanningResponse.JobStatus.SUCCEEDED, planId, null);
            log.info("planning job={} stage=SUCCEEDED planId={} pinCount={}", jobId, planId, normalized.pins().size());
        } catch (Exception exception) {
            log.warn("planning job={} stage=FAILED exception={}", jobId, exception.toString());
            String message = exception instanceof ResponseStatusException status ? status.getReason()
                    : exception instanceof IllegalStateException ? exception.getMessage()
                    : exception instanceof com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException known ? known.getErrorCode().getMessage()
                    : "일정 생성 처리에 실패했습니다. 잠시 후 새 요청으로 시도해 주세요.";
            jobs.update(jobId, PlanningResponse.JobStatus.FAILED, null, message);
        }
    }

    private String encode(GeneratePlanRequest request) {
        try { return objectMapper.writeValueAsString(request); }
        catch (JsonProcessingException exception) { throw new IllegalStateException("여행 조건 직렬화 실패", exception); }
    }

    private static double distanceMeters(PlanContext.Coordinate center, PlaceResult place) {
        if (place.latitude() == null || place.longitude() == null
                || !Double.isFinite(place.latitude()) || !Double.isFinite(place.longitude())
                || Math.abs(place.latitude()) > 90 || Math.abs(place.longitude()) > 180) {
            return Double.POSITIVE_INFINITY;
        }
        double latitudeDelta = Math.toRadians(place.latitude() - center.lat());
        double longitudeDelta = Math.toRadians(place.longitude() - center.lon());
        double haversine = Math.pow(Math.sin(latitudeDelta / 2), 2)
                + Math.cos(Math.toRadians(center.lat())) * Math.cos(Math.toRadians(place.latitude()))
                * Math.pow(Math.sin(longitudeDelta / 2), 2);
        return 6371000 * 2 * Math.asin(Math.sqrt(Math.min(1, haversine)));
    }
}
