package com.yollo.TravelMate.domain.place.source.tourapi.mapper;

import java.util.List;
import java.util.Set;

import org.springframework.stereotype.Component;

import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiInfoItem;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;

@Component
public class TourPlaceDescriptionBuilder {

    private static final Set<String> DESCRIPTIVE_INFORMATION_NAMES = Set.of(
            "체험프로그램",
            "행사소개",
            "행사내용",
            "코스안내",
            "이용요금",
            "주요시설",
            "부대시설"
    );

    public String build(
            TourContentType contentType,
            String sourceCategory,
            String overview,
            List<TourApiInfoItem> informationItems
    ) {
        StringBuilder description = new StringBuilder(contentType.getLabel());
        if (sourceCategory != null && !sourceCategory.equals(contentType.getLabel())) {
            description.append(". ").append(sourceCategory);
        }
        if (overview != null) {
            description.append(". ").append(overview);
        }

        informationItems.stream()
                .filter(this::isDescriptive)
                .forEach(informationItem -> description
                        .append("\n")
                        .append(informationItem.infoName())
                        .append(": ")
                        .append(informationItem.infoText().trim()));
        return description.toString().trim();
    }

    private boolean isDescriptive(TourApiInfoItem informationItem) {
        if (informationItem.infoName() == null || informationItem.infoText() == null) {
            return false;
        }
        return DESCRIPTIVE_INFORMATION_NAMES.contains(informationItem.infoName().trim())
                && !informationItem.infoText().isBlank();
    }
}
