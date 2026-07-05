package com.yollo.TravelMate.domain.tourAPI.enums;


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
}