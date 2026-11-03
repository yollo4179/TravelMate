package com.yollo.TravelMate.domain.place.enums;

import java.util.Arrays;
import java.util.List;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;

public final class PlaceSearchCategories {
    // Search filters must use the same labels that indexing persists in places.category.
    private static final List<String> ALLOWED_VALUES = Arrays.stream(TourContentType.values())
            .map(TourContentType::getLabel)
            .toList();

    private PlaceSearchCategories() {}

    public static List<String> allowedValues() {
        return ALLOWED_VALUES;
    }

    public static void validate(String category) {
        if (category == null || ALLOWED_VALUES.contains(category)) return;
        throw new IllegalArgumentException("Unsupported search category: use an allowed category and keep detailed traits in query");
    }
}
