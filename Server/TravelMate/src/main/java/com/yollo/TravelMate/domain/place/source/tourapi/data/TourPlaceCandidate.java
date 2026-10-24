package com.yollo.TravelMate.domain.place.source.tourapi.data;

import java.util.List;

import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiCommonResult;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiInfoItem;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient.TourApiListItem;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;

public record TourPlaceCandidate(
        TourApiListItem item,
        TourApiCommonResult common,
        String region,
        String city,
        TourContentType contentType,
        String sourceCategory,
        String description,
        List<TourApiInfoItem> informationItems
) {
}
