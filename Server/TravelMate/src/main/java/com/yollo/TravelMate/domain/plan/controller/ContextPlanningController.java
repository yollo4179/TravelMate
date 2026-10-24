package com.yollo.TravelMate.domain.plan.controller;

import java.util.List;
import java.util.UUID;
import com.yollo.TravelMate.domain.plan.data.request.*;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import com.yollo.TravelMate.domain.place.data.response.PlaceSearchResponseDto;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.user.entity.User;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class ContextPlanningController {
    private final ContextPlanningService planningService;

    @PostMapping("/plans/generations")
    public ResponseEntity<PlanningResponse.Job> generate(
            @AuthenticationPrincipal User user,
            @RequestHeader("Idempotency-Key") UUID key,
            @Valid @RequestBody GeneratePlanRequest request
    ) {
        return ResponseEntity.accepted().body(planningService.generate(user.getUid(), key, request));
    }

    @PostMapping("/plans")
    public ResponseEntity<PlanningResponse.Draft> create(
            @AuthenticationPrincipal User user,
            @RequestHeader("Idempotency-Key") UUID key,
            @Valid @RequestBody GeneratePlanRequest request
    ) {
        return ResponseEntity.status(201).body(planningService.create(user.getUid(), key, request));
    }

    @GetMapping("/planning-jobs/{jobId}")
    public PlanningResponse.Job job(@AuthenticationPrincipal User user, @PathVariable("jobId") UUID jobId) {
        return planningService.job(jobId, user.getUid());
    }

    @GetMapping("/plans/{planId}")
    public PlanningResponse.Draft plan(@AuthenticationPrincipal User user, @PathVariable("planId") long planId) {
        return planningService.plan(planId, user.getUid());
    }

    @PostMapping("/places/search")
    public List<PlaceSearchResponseDto> search(
            @Valid @RequestBody PlaceSearchRequest request,
            @RequestParam(name = "rankingMode", defaultValue = "RERANKED") PlaceSemanticSearchService.RankingMode rankingMode
    ) {
        return planningService.search(request.context(), request.query(), request.limit(), rankingMode)
                .stream().map(PlaceSearchResponseDto::from).toList();
    }

    public record PlaceSearchRequest(
            @NotNull @Valid PlanContext context,
            @NotBlank @Size(max = 2000) String query,
            @Min(1) @Max(20) int limit
    ) {}

    @ExceptionHandler(org.springframework.web.server.ResponseStatusException.class)
    public ResponseEntity<java.util.Map<String, String>> invalidRequest(
            org.springframework.web.server.ResponseStatusException exception
    ) {
        return ResponseEntity.status(exception.getStatusCode()).body(
                java.util.Map.of("errorMessage", java.util.Objects.toString(exception.getReason(), "요청을 처리할 수 없습니다."))
        );
    }
}
