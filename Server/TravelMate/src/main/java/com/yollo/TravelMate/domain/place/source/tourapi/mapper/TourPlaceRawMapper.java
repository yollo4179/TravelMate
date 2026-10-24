package com.yollo.TravelMate.domain.place.source.tourapi.mapper;

import java.util.List;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.place.source.tourapi.classification.LclsSystemCodeLookup;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiCommonResult;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiInfoItem;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient.TourApiListItem;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourAreaCode;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.place.source.tourapi.data.TourPlaceCandidate;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository.RawRow;

import lombok.RequiredArgsConstructor;

@Component
@RequiredArgsConstructor
public class TourPlaceRawMapper {

    private static final Logger log = LoggerFactory.getLogger(TourPlaceRawMapper.class);

    private final ObjectMapper objectMapper;
    private final LclsSystemCodeLookup categoryLookup;
    private final TourPlaceDescriptionBuilder descriptionBuilder;

    public Optional<TourPlaceCandidate> map(RawRow rawRow) {
        try {
            TourContentType contentType = TourContentType.fromContentTypeId(rawRow.tourContentTypeId());
            if (contentType == null || rawRow.rawList() == null) {
                log.warn(
                        "필수 TourAPI 원본이 없어 변환을 건너뜁니다: tourContentId={}, contentTypeId={}",
                        rawRow.tourContentId(),
                        rawRow.tourContentTypeId()
                );
                return Optional.empty();
            }

            JsonNode listNode = objectMapper.readTree(rawRow.rawList());
            TourApiListItem listItem = TourApiPlaceListClient.toListItem(listNode);
            TourApiCommonResult commonResult = parseCommonResult(rawRow.rawCommon());
            List<TourApiInfoItem> informationItems = parseInformationItems(rawRow.rawInfo());
            TourAreaCode areaCode = TourAreaCode.fromCode(listItem.areaCode());
            String sourceCategory = categoryLookup.resolveName(
                    listItem.lclsSystm1(),
                    listItem.lclsSystm2(),
                    listItem.lclsSystm3()
            );
            String description = descriptionBuilder.build(
                    contentType,
                    sourceCategory,
                    commonResult.overview(),
                    informationItems
            );

            return Optional.of(new TourPlaceCandidate(
                    listItem,
                    commonResult,
                    areaCode == null ? null : areaCode.getRegion(),
                    extractCity(listItem.addr1()),
                    contentType,
                    sourceCategory,
                    description,
                    informationItems
            ));
        } catch (Exception exception) {
            log.error("TourAPI 원본 변환 실패: tourContentId={}", rawRow.tourContentId(), exception);
            return Optional.empty();
        }
    }

    private TourApiCommonResult parseCommonResult(String rawCommon) throws Exception {
        if (rawCommon == null) {
            return new TourApiCommonResult(null, null, null, null);
        }
        return TourApiPlaceDetailClient.toCommonResult(objectMapper.readTree(rawCommon));
    }

    private List<TourApiInfoItem> parseInformationItems(String rawInformation) throws Exception {
        if (rawInformation == null) {
            return List.of();
        }
        return TourApiPlaceDetailClient.toInfoResult(objectMapper.readTree(rawInformation)).items();
    }

    private String extractCity(String address) {
        if (address == null || address.isBlank()) {
            return null;
        }
        String[] addressTokens = address.trim().split("\\s+");
        if (addressTokens.length < 2) {
            return null;
        }
        return addressTokens[1].replaceAll("(시|군|구)$", "");
    }
}
