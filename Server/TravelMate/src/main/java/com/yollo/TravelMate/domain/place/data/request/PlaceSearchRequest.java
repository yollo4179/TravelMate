package com.yollo.TravelMate.domain.place.data.request;

import java.util.List;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService.RankingMode;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.hibernate.validator.constraints.CodePointLength;

public record PlaceSearchRequest(
        @NotBlank @CodePointLength(max = 2000) String query,
        @CodePointLength(max = 200) @Pattern(regexp = "(?s).*\\S.*") String region,
        @CodePointLength(max = 200) @Pattern(regexp = "(?s).*\\S.*") String city,
        @CodePointLength(max = 200) @Pattern(regexp = "(?s).*\\S.*") String category,
        List<@NotNull @Positive Long> excludePlaceIds,
        @Valid SearchArea area,
        @Min(1) @Max(20) Integer limit,
        @NotNull RankingMode rankingMode
) {
    public PlaceSearchRequest {
        limit = limit == null ? 10 : limit;
        rankingMode = rankingMode == null ? RankingMode.RERANKED : rankingMode;
        excludePlaceIds = excludePlaceIds == null ? List.of() : List.copyOf(excludePlaceIds);
        if (excludePlaceIds.stream().distinct().count() != excludePlaceIds.size()) {
            throw new IllegalArgumentException("Duplicate excluded place IDs");
        }
    }

    public enum AreaType { CIRCLE }

    @JsonAnySetter
    public void rejectUnknownField(String name, JsonNode value) {
        throw new IllegalArgumentException("Unknown search field: " + name);
    }

    public record SearchArea(
            @NotNull AreaType type,
            @NotNull @Valid Coordinate center,
            @NotNull @Min(500) @Max(10000) Integer radiusMeters
    ) {
        @JsonAnySetter
        public void rejectUnknownField(String name, JsonNode value) {
            throw new IllegalArgumentException("Unknown area field: " + name);
        }

        public PlanContext.Area toPlanArea() {
            return new PlanContext.Area(
                    PlanContext.AreaType.CIRCLE,
                    new PlanContext.Coordinate(center.lat(), center.lon()),
                    radiusMeters,
                    null
            );
        }
    }

    public record Coordinate(
            @NotNull @DecimalMin("-90") @DecimalMax("90") Double lat,
            @NotNull @DecimalMin("-180") @DecimalMax("180") Double lon
    ) {
        @JsonAnySetter
        public void rejectUnknownField(String name, JsonNode value) {
            throw new IllegalArgumentException("Unknown coordinate field: " + name);
        }
    }
}
