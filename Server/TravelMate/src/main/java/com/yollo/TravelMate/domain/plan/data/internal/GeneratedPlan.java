package com.yollo.TravelMate.domain.plan.data.internal;

import java.util.List;

public record GeneratedPlan(
        String planTitle,
        String planDescription,
        List<GeneratedPin> pins
) {
    public record GeneratedPin(
            Long placeId,
            Integer sequence,
            String activity,
            String reason
    ) {}
}