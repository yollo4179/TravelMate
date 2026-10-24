package com.yollo.TravelMate.domain.plan.data.request;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;
import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;

public record PlanContext(
        @NotNull @Valid Area area,
        @NotNull @Valid Location origin,
        @Valid Location destination,
        @NotNull @com.fasterxml.jackson.annotation.JsonFormat(
                shape = com.fasterxml.jackson.annotation.JsonFormat.Shape.STRING,
                without = com.fasterxml.jackson.annotation.JsonFormat.Feature.ADJUST_DATES_TO_CONTEXT_TIME_ZONE
        ) OffsetDateTime startAt,
        @NotNull @com.fasterxml.jackson.annotation.JsonFormat(
                shape = com.fasterxml.jackson.annotation.JsonFormat.Shape.STRING,
                without = com.fasterxml.jackson.annotation.JsonFormat.Feature.ADJUST_DATES_TO_CONTEXT_TIME_ZONE
        ) OffsetDateTime endAt,
        @NotNull TransportMode transportMode,
        @NotNull Objective objective,
        @NotNull @Valid Preferences preferences,
        @NotNull @Size(max = 10) List<@Valid CategoryRequirement> categoryRequirements,
        @Size(max = 2000) String additionalRequest,
        @NotNull UnknownHoursPolicy unknownHoursPolicy
) {
    public enum AreaType { CIRCLE, REGION }
    public enum LocationSource { GPS, SELECTED_POINT }
    public enum TransportMode { WALK, CAR }
    public enum Objective { DISTANCE, DURATION }
    public enum Pace { RELAXED, NORMAL }
    public enum UnknownHoursPolicy { EXCLUDE, ALLOW_WITH_WARNING }
    public enum Category { CAFE }

    public record Coordinate(
            @NotNull @DecimalMin("-90") @DecimalMax("90") Double lat,
            @NotNull @DecimalMin("-180") @DecimalMax("180") Double lon
    ) {}

    public record Area(
            @NotNull AreaType type,
            @Valid Coordinate center,
            @Min(500) @Max(10000) Integer radiusMeters,
            String regionId
    ) {
        @JsonIgnore
        @AssertTrue(message = "검색 범위의 중심과 반경 또는 지역 ID가 필요합니다.")
        public boolean isValidArea() {
            if (type == AreaType.CIRCLE) return center != null && radiusMeters != null;
            return type == AreaType.REGION && regionId != null && !regionId.isBlank();
        }
    }

    public record Location(
            @NotNull @Valid Coordinate coordinate,
            @NotBlank @Size(max = 200) String label,
            @NotNull LocationSource source
    ) {}

    public record Preferences(
            @NotNull @Size(max = 20) List<@NotBlank @Size(max = 100) String> themes,
            @NotNull @Size(max = 20) List<@NotBlank @Size(max = 100) String> avoid,
            @NotNull Pace pace,
            @Min(1) @Max(100) int partySize,
            @PositiveOrZero Long budgetKrw
    ) {}

    public record CategoryRequirement(@NotNull Category category, @Min(1) @Max(6) int minCount) {}

    @JsonIgnore
    @AssertTrue(message = "여행 시간은 한국 시간 기준 같은 날 최대 12시간이어야 합니다.")
    public boolean isValidTimeWindow() {
        if (startAt == null || endAt == null) return true;
        var koreaOffset = java.time.ZoneOffset.ofHours(9);
        long minutes = Duration.between(startAt, endAt).toMinutes();
        return minutes > 0 && minutes <= 720
                && startAt.withOffsetSameInstant(koreaOffset).toLocalDate()
                    .equals(endAt.withOffsetSameInstant(koreaOffset).toLocalDate());
    }
}
