package com.yollo.TravelMate.domain.place.source.tourapi;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.stream.Stream;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiInfoItem;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourCoordinateStatus;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceCoordinateValidator;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceDescriptionBuilder;

class TourPlaceDataQualityTest {

    private final TourPlaceDescriptionBuilder descriptionBuilder = new TourPlaceDescriptionBuilder();
    private final TourPlaceCoordinateValidator coordinateValidator = new TourPlaceCoordinateValidator();

    static Stream<String> informationNames() {
        return Stream.of("입 장 료", "이용가능시설", "외국어 안내서비스", "내국인 예약안내", "새로운 공급자 필드");
    }

    @ParameterizedTest
    @MethodSource("informationNames")
    void supplementalFactsRemainSearchable(String informationName) {
        String description = descriptionBuilder.build(
                TourContentType.관광지,
                "근린공원",
                "동네 산책 공간",
                List.of(new TourApiInfoItem(informationName, "제공된 사실", "0"))
        );
        assertTrue(description.contains(informationName.replace(" ", "") + ": 제공된 사실"));
    }

    @Test
    void blankOverviewCanUseFacilitiesWithoutInventingOtherFacts() {
        String description = descriptionBuilder.build(
                TourContentType.관광지,
                "근린공원",
                null,
                List.of(new TourApiInfoItem("이용가능시설", "팔각정", "0"))
        );
        assertEquals("관광지. 근린공원\n이용가능시설: 팔각정", description);
        assertFalse(description.contains("한강"));
    }

    @Test
    void htmlAndSpacingAreNormalizedAndDuplicateFactsAreCollapsed() {
        String description = descriptionBuilder.build(
                TourContentType.관광지,
                "관광지",
                "<p>숲 &amp; 산책</p><br>쉼터",
                List.of(
                        new TourApiInfoItem("입 장 료", "무료<br>어린이&nbsp;포함", "0"),
                        new TourApiInfoItem("입장료", "무료\n어린이 포함", "1"),
                        new TourApiInfoItem("화장실", "<br>&nbsp;", "2"),
                        new TourApiInfoItem(" ", "의미 없는 제목", "3")
                )
        );
        assertEquals("관광지. 숲 & 산책\n쉼터\n입장료: 무료\n어린이 포함", description);
    }

    static Stream<Arguments> coordinates() {
        return Stream.of(
                Arguments.of(37.57, 126.98, TourCoordinateStatus.VALID),
                Arguments.of(33.25, 126.56, TourCoordinateStatus.VALID),
                Arguments.of(37.24, 131.87, TourCoordinateStatus.VALID),
                Arguments.of(19.69442748, 117.9925662504, TourCoordinateStatus.OUTSIDE_DOMESTIC_RANGE),
                Arguments.of(0.0, 0.0, TourCoordinateStatus.OUTSIDE_DOMESTIC_RANGE),
                Arguments.of(127.0, 37.0, TourCoordinateStatus.OUTSIDE_DOMESTIC_RANGE),
                Arguments.of(Double.NaN, 127.0, TourCoordinateStatus.NON_FINITE),
                Arguments.of(37.0, Double.POSITIVE_INFINITY, TourCoordinateStatus.NON_FINITE),
                Arguments.of(null, 127.0, TourCoordinateStatus.MISSING)
        );
    }

    @ParameterizedTest
    @MethodSource("coordinates")
    void obviousCoordinateErrorsAreRejectedWhileDomesticIslandsRemainValid(
            Double latitude,
            Double longitude,
            TourCoordinateStatus expected
    ) {
        assertEquals(expected, coordinateValidator.validate(latitude, longitude));
    }
}
