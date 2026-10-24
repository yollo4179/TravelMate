package com.yollo.TravelMate.domain.place.data.internal;

public record PlaceCreateCommand(
        String name,
        String description,
        String region,
        String city,
        String category,
        String sourceCategory,
        Double latitude,
        Double longitude,
        String tourContentId,
        String tourContentTypeId,
        String imageUrl,
        String homepageUrl,
        float[] embedding
) {
}
