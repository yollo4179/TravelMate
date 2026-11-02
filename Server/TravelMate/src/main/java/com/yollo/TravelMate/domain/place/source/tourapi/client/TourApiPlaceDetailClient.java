package com.yollo.TravelMate.domain.place.source.tourapi.client;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.StreamSupport;

import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourApiFailureReason;
import com.yollo.TravelMate.domain.place.source.tourapi.support.TourPlaceTextNormalizer;
import com.yollo.TravelMate.util.UrlUtil;

import lombok.RequiredArgsConstructor;

@Component
@RequiredArgsConstructor
public class TourApiPlaceDetailClient {

    private static final int INFO_MAX_ROWS = 100;

    private final TourApiResponseClient responseClient;
    private final ObjectMapper objectMapper;
    private final TourApiUrlBuilder urlBuilder;

    public record TourApiCommonResult(
            String overview,
            String homepageUrl,
            String firstImage,
            String rawJson
    ) {
    }

    public TourApiCommonResult fetchCommon(String contentId) {
        var page = responseClient.fetch(urlBuilder.detailCommon(contentId));
        if (page.totalCount() == 0) {
            return new TourApiCommonResult(null, null, null, null);
        }
        requireSingleItem(page);
        return toCommonResult(page.items().get(0));
    }

    public static TourApiCommonResult toCommonResult(JsonNode item) {
        if (!item.isObject() || item.isEmpty()) {
            throw new IllegalArgumentException("TourAPI 공통 정보는 비어 있지 않은 객체여야 합니다.");
        }
        String overview = blankToNull(item.path("overview").asText(null));
        String homepage = UrlUtil.extractHomepageUrl(item.path("homepage").asText(null));
        String image = blankToNull(item.path("firstimage").asText(null));
        return new TourApiCommonResult(overview, homepage, image, item.toString());
    }

    private static String blankToNull(String source) {
        return (source == null || source.isBlank()) ? null : source.trim();
    }
 
    public TourApiIntroResult fetchIntro(
            String contentId,
            String contentTypeId
    ) {
        var page = responseClient.fetch(urlBuilder.detail("/detailIntro2", contentId, contentTypeId, 1));
        if (page.totalCount() == 0) {
            return new TourApiIntroResult(contentId, null);
        }
        requireSingleItem(page);
        return new TourApiIntroResult(contentId, page.items().get(0).toString());
    }

    private void requireSingleItem(TourApiResponseClient.ResponsePage page) {
        if (page.totalCount() != 1 || page.items().size() != 1) {
            throw inconsistentPage(page.rawResponse());
        }
    }

    public TourApiInfoResult fetchInfoItems(
            String contentId,
            String contentTypeId
    ) {
        List<JsonNode> allRawNodes = new ArrayList<>();
        int expectedTotal = -1;
        int pageNumber = 1;
        while (true) {
            var page = responseClient.fetch(urlBuilder.detail(
                    "/detailInfo2",
                    contentId,
                    contentTypeId,
                    INFO_MAX_ROWS,
                    pageNumber
            ));
            if (expectedTotal >= 0 && expectedTotal != page.totalCount()) {
                throw inconsistentPage(page.rawResponse());
            }
            expectedTotal = page.totalCount();
            allRawNodes.addAll(page.items());
            if (allRawNodes.size() > expectedTotal) {
                throw inconsistentPage(page.rawResponse());
            }
            if (allRawNodes.size() == expectedTotal) {
                break;
            }
            if (pageNumber * (long) INFO_MAX_ROWS >= expectedTotal) {
                throw inconsistentPage(page.rawResponse());
            }
            pageNumber++;
        }
        if (allRawNodes.isEmpty()) {
            return new TourApiInfoResult(List.of(), null);
        }
        var combined = objectMapper.createArrayNode();
        allRawNodes.forEach(combined::add);
        return toInfoResult(combined);
    }

    private TourApiCollectionException inconsistentPage(String rawResponse) {
        return TourApiCollectionException.builder()
                .reason(TourApiFailureReason.INCONSISTENT_PAGE)
                .rawResponse(rawResponse)
                .build();
    }

    public static TourApiInfoResult toInfoResult(JsonNode itemNode) {
        if (!itemNode.isArray() && !itemNode.isObject()) {
            throw new IllegalArgumentException("TourAPI 추가 안내는 객체 또는 배열이어야 합니다.");
        }
        List<TourApiInfoItem> items = itemNode.isArray()
                ? StreamSupport.stream(itemNode.spliterator(), false)
                        .map(TourApiPlaceDetailClient::toInfoItem)
                        .toList()
                : List.of(toInfoItem(itemNode));
        String rawJson = items.isEmpty() ? null : itemNode.toString();
        return new TourApiInfoResult(items, rawJson);
    }

    public static TourApiInfoItem toInfoItem(JsonNode node) {
        if (!node.isObject() || node.isEmpty()) {
            throw new IllegalArgumentException("TourAPI 추가 안내 항목은 비어 있지 않은 객체여야 합니다.");
        }
        return new TourApiInfoItem(
                node.path("infoname").asText(null),
                node.path("infotext").asText(null),
                node.path("serialnum").asText(null)
        );
    }
 
    public record TourApiIntroResult(
            String tourContentId,
            String rawIntroJson
    ) {
    }
 
    public record TourApiInfoItem(
            String infoName,
            String infoText,
            String serialNum
    ) {
        public boolean hasContent() {
            return !TourPlaceTextNormalizer.normalizeHeading(infoName).isBlank()
                    && !TourPlaceTextNormalizer.normalize(infoText).isBlank();
        }
    }

    public record TourApiInfoResult(
            List<TourApiInfoItem> items,
            String rawJson
    ) {
    }
}
