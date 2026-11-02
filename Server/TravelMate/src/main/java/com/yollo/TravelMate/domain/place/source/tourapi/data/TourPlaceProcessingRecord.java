package com.yollo.TravelMate.domain.place.source.tourapi.data;

import com.yollo.TravelMate.domain.place.source.tourapi.code.TourCoordinateStatus;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourPlaceProcessingReason;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository.RawRow;

import lombok.Builder;

@Builder
public record TourPlaceProcessingRecord(
        String tourContentId,
        String originalListJson,
        String originalCommonJson,
        String originalInfoJson,
        String normalizedDescription,
        Double normalizedLatitude,
        Double normalizedLongitude,
        TourCoordinateStatus coordinateStatus,
        TourPlaceProcessingReason reason
) {
    public static TourPlaceProcessingRecord from(
            RawRow original,
            TourPlaceCandidate normalized,
            TourCoordinateStatus coordinateStatus,
            TourPlaceProcessingReason reason
    ) {
        return TourPlaceProcessingRecord.builder()
                .tourContentId(original.tourContentId())
                .originalListJson(original.rawList())
                .originalCommonJson(original.rawCommon())
                .originalInfoJson(original.rawInfo())
                .normalizedDescription(normalized == null ? null : normalized.description())
                .normalizedLatitude(normalized == null ? null : normalized.item().mapY())
                .normalizedLongitude(normalized == null ? null : normalized.item().mapX())
                .coordinateStatus(coordinateStatus)
                .reason(reason)
                .build();
    }
}
