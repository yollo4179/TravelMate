package com.yollo.TravelMate.domain.pin.data.internal;

import java.util.List;

public record GeneratedPinActivities(
        Long pinId,
        String mode,          // "GROUNDED" | "GENERIC"
        List<GeneratedActivity> activities
) {
    public record GeneratedActivity(
            Integer sequence,
            String activity,
            String reason,
            Integer estimatedMinutes  // null 허용
    ) {}
}
 