package com.yollo.TravelMate.domain.place.data.response;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult;

public record PlaceSearchResponseDto(
        Long placeId,
        String name,
        String description,
        String region,
        String city,
        String category,
        Double latitude,
        Double longitude,
        Double semanticScore,
        float rerankScore,
        String tourContentId,
        String imageUrl,
        String homepageUrl
) {

    public static PlaceSearchResponseDto from(PlaceSemanticSearchResult searchResult) {
        PlaceResult place = searchResult.place();
        return new PlaceSearchResponseDto(
                place.id(),
                place.name(),
                place.description(),
                place.region(),
                place.city(),
                place.category(),
                place.latitude(),
                place.longitude(),
                place.similarity(),
                searchResult.rerankScore(),
                place.tourContentId(),
                place.imageUrl(),
                place.homepageUrl()
        );
    }
}
