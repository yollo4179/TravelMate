package com.yollo.TravelMate.domain.place.data.result;



public record PlaceResult(
        Long id,
        String name,
        String description,
        String region,
        String city,
        String category,
        String sourceCategory,
        Double latitude,
        Double longitude,
        Double similarity,
        String tourContentId,
        String imageUrl,      
        String homepageUrl
) {}


