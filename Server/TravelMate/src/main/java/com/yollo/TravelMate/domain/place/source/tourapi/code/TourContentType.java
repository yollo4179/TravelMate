package com.yollo.TravelMate.domain.place.source.tourapi.code;

import java.util.Arrays;

public enum TourContentType {
    관광지("12", "관광지"),
    문화시설("14", "문화시설"),
    축제공연행사("15", "축제공연행사"),
    여행코스("25", "여행코스"),
    레포츠("28", "레포츠"),
    숙박("32", "숙박"),
    쇼핑("38", "쇼핑"),
    음식점("39", "음식점");

    private final String contentTypeId;
    private final String label;

    TourContentType(String contentTypeId, String label) {
        this.contentTypeId = contentTypeId;
        this.label = label;
    }
    public String getContentTypeId() { return contentTypeId; }
    public String getLabel() { return label; }

    /** raw JSON 재파싱(processRaw)용 - contentTypeId로 역조회. 못 찾으면 null. */
    public static TourContentType fromContentTypeId(String contentTypeId) {
        return Arrays.stream(values())
                .filter(v -> v.contentTypeId.equals(contentTypeId))
                .findFirst()
                .orElse(null);
    }
}
