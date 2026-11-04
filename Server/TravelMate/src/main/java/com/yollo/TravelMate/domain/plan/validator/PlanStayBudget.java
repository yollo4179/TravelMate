package com.yollo.TravelMate.domain.plan.validator;

import java.time.Duration;
import java.util.Collection;
import java.util.Map;
import java.util.stream.Collectors;
import java.util.stream.IntStream;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;

/**
 * One time rule for both the plan prompt and the draft validator, so the model is never asked for more stops than
 * the validator accepts. Besides stay time, every walking leg (origin to the first stop, between stops, and the last
 * stop to a destination when one is set) reserves a fixed allowance: live drafts filled a two-hour window with two
 * hour-long stays and left no time to walk between them. The allowance is a planning reserve, not a measured route.
 */
public final class PlanStayBudget {
    public static final int MAX_STOPS = 6;
    // About 1 km at walking pace plus detours, for a leg inside the 2 km search circle. Generation accepts walking only.
    public static final int WALKING_LEG_MINUTES = 15;
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

    public static int legs(int stops, GeneratePlanRequest request) {
        if (stops == 0) return 0;
        return stops + (request.context().destination() == null ? 0 : 1);
    }

    /** Stay time plus the walking allowance for visiting exactly these places. */
    public static long requiredMinutes(Collection<Long> placeIds, GeneratePlanRequest request) {
        return totalStayMinutes(placeIds, request) + (long) legs(placeIds.size(), request) * WALKING_LEG_MINUTES;
    }

    /** Required stops always count; default stays and their legs fill the rest of the window, never past MAX_STOPS. */
    public static int maxStops(GeneratePlanRequest request) {
        var required = requiredStays(request);
        int requiredStay = required.values().stream().mapToInt(Integer::intValue).sum();
        int defaultStay = defaultStayMinutes(request);
        long available = availableMinutes(request);
        return IntStream.rangeClosed(required.size(), MAX_STOPS)
                .filter(stops -> requiredStay + (long) (stops - required.size()) * defaultStay
                        + (long) legs(stops, request) * WALKING_LEG_MINUTES <= available)
                .max()
                .orElse(required.size());
    }

    private static Map<Long, Integer> requiredStays(GeneratePlanRequest request) {
        return request.requiredStops().stream().collect(Collectors.toMap(
                GeneratePlanRequest.RequiredStop::placeId,
                GeneratePlanRequest.RequiredStop::stayMinutes
        ));
    }
}
