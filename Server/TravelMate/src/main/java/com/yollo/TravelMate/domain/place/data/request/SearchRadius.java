package com.yollo.TravelMate.domain.place.data.request;

import java.util.Map;

/** One radius bound for request validation, the model tool schema and the UI slider. */
public final class SearchRadius {
    public static final int MIN_METERS = 500;
    public static final int MAX_METERS = 10000;

    private SearchRadius() {}

    public static Map<String, Integer> bounds() {
        return Map.of("min", MIN_METERS, "max", MAX_METERS);
    }
}
