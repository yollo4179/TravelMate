package com.yollo.TravelMate.domain.place.source.tourapi.client;

import com.yollo.TravelMate.domain.place.source.tourapi.code.TourApiFailureReason;

import lombok.Builder;
import lombok.Getter;

@Getter
public final class TourApiCollectionException extends IllegalStateException {

    private final TourApiFailureReason reason;
    private final String rawResponse;

    @Builder
    private TourApiCollectionException(
            TourApiFailureReason reason,
            String rawResponse,
            Throwable cause
    ) {
        super("TourAPI 수집을 중단합니다: " + reason, cause);
        this.reason = reason;
        this.rawResponse = rawResponse;
    }
}
