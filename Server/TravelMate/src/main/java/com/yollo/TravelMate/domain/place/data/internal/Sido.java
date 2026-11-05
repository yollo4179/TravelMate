package com.yollo.TravelMate.domain.place.data.internal;

import java.util.Arrays;
import java.util.List;
import java.util.Optional;

/**
 * The 17 provinces and metropolitan cities, labelled as places.region stores them (TourAPI short names).
 * LiLi picks one of these labels for the area a user asks about; the server compares it with the data it holds.
 */
public enum Sido {
    SEOUL("서울"),
    BUSAN("부산"),
    DAEGU("대구"),
    INCHEON("인천"),
    GWANGJU("광주"),
    DAEJEON("대전"),
    ULSAN("울산"),
    SEJONG("세종"),
    GYEONGGI("경기"),
    GANGWON("강원"),
    CHUNGBUK("충북"),
    CHUNGNAM("충남"),
    JEONBUK("전북"),
    JEONNAM("전남"),
    GYEONGBUK("경북"),
    GYEONGNAM("경남"),
    JEJU("제주");

    private final String label;

    Sido(String label) {
        this.label = label;
    }

    public String label() {
        return label;
    }

    public static List<String> labels() {
        return Arrays.stream(values()).map(Sido::label).toList();
    }

    public static Optional<Sido> fromLabel(String label) {
        if (label == null) return Optional.empty();
        String trimmed = label.strip();
        return Arrays.stream(values()).filter(sido -> sido.label.equals(trimmed)).findFirst();
    }
}
