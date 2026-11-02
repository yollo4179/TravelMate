package com.yollo.TravelMate.domain.place.source.tourapi.mapper;

import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import org.springframework.stereotype.Component;

import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiInfoItem;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.place.source.tourapi.support.TourPlaceTextNormalizer;

@Component
public class TourPlaceDescriptionBuilder {

    public String build(
            TourContentType contentType,
            String sourceCategory,
            String overview,
            List<TourApiInfoItem> informationItems
    ) {
        String heading = Stream.of(contentType.getLabel(), sourceCategory, overview)
                .map(TourPlaceTextNormalizer::normalize)
                .filter(section -> !section.isBlank())
                .distinct()
                .collect(Collectors.joining(". "));
        // 제공자가 추가한 시설·요금·해설 필드도 검색 근거가 되므로 고정 허용 목록으로 버리지 않는다.
        Stream<String> supplementalSections = informationItems.stream()
                .filter(TourApiInfoItem::hasContent)
                .map(item -> TourPlaceTextNormalizer.normalizeHeading(item.infoName())
                        + ": " + TourPlaceTextNormalizer.normalize(item.infoText()));
        return Stream.concat(Stream.of(heading), supplementalSections)
                .distinct()
                .collect(Collectors.joining("\n"));
    }
}
