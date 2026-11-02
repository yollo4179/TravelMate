package com.yollo.TravelMate.domain.place.data.request;

import java.util.List;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;

public record PlaceSearchContext(
        @Size(max = 200) @Pattern(regexp = "(?s).*\\S.*") String region,
        @Size(max = 200) @Pattern(regexp = "(?s).*\\S.*") String city,
        @Size(max = 200) @Pattern(regexp = "(?s).*\\S.*") String category,
        List<@NotNull @Positive Long> excludePlaceIds,
        @Valid PlaceSearchRequest.SearchArea area
) {
    public PlaceSearchContext {
        excludePlaceIds = excludePlaceIds == null ? List.of() : List.copyOf(excludePlaceIds);
        if (excludePlaceIds.stream().distinct().count() != excludePlaceIds.size()) {
            throw new IllegalArgumentException("Duplicate excluded place IDs");
        }
    }

    @JsonAnySetter
    public void rejectUnknownField(String name, JsonNode value) {
        throw new IllegalArgumentException("Unknown search context field: " + name);
    }
}
