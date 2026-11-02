package com.yollo.TravelMate.domain.place.source.tourapi.mapper;

import org.springframework.stereotype.Component;

import com.yollo.TravelMate.domain.place.source.tourapi.code.TourCoordinateStatus;

@Component
public class TourPlaceCoordinateValidator {

    // 도서 지역까지 여유 있게 포함하는 수집 오류 검사용 범위이며 행정구역 경계를 판정하지 않는다.
    private static final double MIN_LATITUDE = 32.0;
    private static final double MAX_LATITUDE = 40.0;
    private static final double MIN_LONGITUDE = 123.0;
    private static final double MAX_LONGITUDE = 133.0;

    public TourCoordinateStatus validate(
            Double latitude,
            Double longitude
    ) {
        if (latitude == null || longitude == null) {
            return TourCoordinateStatus.MISSING;
        }
        if (!Double.isFinite(latitude) || !Double.isFinite(longitude)) {
            return TourCoordinateStatus.NON_FINITE;
        }
        if (latitude < MIN_LATITUDE || latitude > MAX_LATITUDE
                || longitude < MIN_LONGITUDE || longitude > MAX_LONGITUDE) {
            return TourCoordinateStatus.OUTSIDE_DOMESTIC_RANGE;
        }
        return TourCoordinateStatus.VALID;
    }
}
