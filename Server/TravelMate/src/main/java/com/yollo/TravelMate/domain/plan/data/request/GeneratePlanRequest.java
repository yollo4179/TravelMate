package com.yollo.TravelMate.domain.plan.data.request;

import java.time.OffsetDateTime;
import java.util.List;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;

public record GeneratePlanRequest(
        @NotNull @Valid PlanContext context,
        @NotNull InputMethod inputMethod,
        @NotNull @Size(max = 6) List<@Valid RequiredStop> requiredStops,
        // Set by LiLi's turn, not by the client form; candidate search uses it instead of themes alone.
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        @Size(max = 300) String searchQuery
) {
    public GeneratePlanRequest(PlanContext context, InputMethod inputMethod, List<RequiredStop> requiredStops) {
        this(context, inputMethod, requiredStops, null);
    }

    public GeneratePlanRequest withSearchQuery(String query) {
        return new GeneratePlanRequest(context, inputMethod, requiredStops, query);
    }

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
