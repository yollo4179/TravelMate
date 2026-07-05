package com.yollo.TravelMate.domain.tourAPI.enums;



public enum TourAreaCode {
    서울("1", "서울"),
    인천("2", "인천"),
    대전("3", "대전"),
    대구("4", "대구"),
    광주("5", "광주"),
    부산("6", "부산"),
    울산("7", "울산"),
    세종("8", "세종"),
    경기("31", "경기"),
    강원("32", "강원"),
    충북("33", "충북"),
    충남("34", "충남"),
    경북("35", "경북"),
    경남("36", "경남"),
    전북("37", "전북"),
    전남("38", "전남"),
    제주("39", "제주");

    private final String areaCode;
    private final String region;   // 기존 City.getRegion()과 매칭되는 광역명

    TourAreaCode(String areaCode, String region) {
        this.areaCode = areaCode;
        this.region = region;
    }
    public String getAreaCode() { return areaCode; }
    public String getRegion() { return region; }
}