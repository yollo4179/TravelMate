package com.yollo.TravelMate.domain.plan.data.request;

import java.time.OffsetDateTime;
import java.util.List;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;

public record GeneratePlanRequest(
        @NotNull @Valid PlanContext context,
        @NotNull InputMethod inputMethod,
        @NotNull @Size(max = 6) List<@Valid RequiredStop> requiredStops
) {
    public enum InputMethod { TEXT, VOICE }
    public record RequiredStop(
            @NotNull @Positive Long placeId,
            @Min(10) @Max(720) int stayMinutes,
            @com.fasterxml.jackson.annotation.JsonFormat(
                    shape = com.fasterxml.jackson.annotation.JsonFormat.Shape.STRING,
                    without = com.fasterxml.jackson.annotation.JsonFormat.Feature.ADJUST_DATES_TO_CONTEXT_TIME_ZONE
            ) OffsetDateTime fixedStartAt
    ) {}
}
