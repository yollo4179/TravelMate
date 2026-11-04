package com.yollo.TravelMate.domain.plan.validator;

import java.time.Duration;
import java.util.Collection;
import java.util.Map;
import java.util.stream.Collectors;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;

/**
 * One stay-time rule for both the plan prompt and the draft validator, so the model is never asked for more
 * stops than the validator will accept. It bounds stay time only; travel time between stops is not checked.
 */
public final class PlanStayBudget {
    public static final int MAX_STOPS = 6;
    private static final int RELAXED_STAY_MINUTES = 60;
    private static final int DEFAULT_STAY_MINUTES = 40;

    private PlanStayBudget() {}

    public static int defaultStayMinutes(GeneratePlanRequest request) {
        return request.context().preferences().pace() == PlanContext.Pace.RELAXED ? RELAXED_STAY_MINUTES : DEFAULT_STAY_MINUTES;
    }

    public static long availableMinutes(GeneratePlanRequest request) {
        return Duration.between(request.context().startAt(), request.context().endAt()).toMinutes();
    }

    public static int totalStayMinutes(Collection<Long> placeIds, GeneratePlanRequest request) {
        var stayById = requiredStays(request);
        int defaultStay = defaultStayMinutes(request);
        return placeIds.stream().mapToInt(placeId -> stayById.getOrDefault(placeId, defaultStay)).sum();
    }

    /** Required stops always count; the remaining time is filled with default stays, never past MAX_STOPS. */
    public static int maxStops(GeneratePlanRequest request) {
        var required = requiredStays(request);
        long remaining = availableMinutes(request) - required.values().stream().mapToInt(Integer::intValue).sum();
        long optional = Math.max(0, remaining / defaultStayMinutes(request));
        return (int) Math.min(MAX_STOPS, required.size() + optional);
    }

    private static Map<Long, Integer> requiredStays(GeneratePlanRequest request) {
        return request.requiredStops().stream().collect(Collectors.toMap(
                GeneratePlanRequest.RequiredStop::placeId,
                GeneratePlanRequest.RequiredStop::stayMinutes
        ));
    }
}
