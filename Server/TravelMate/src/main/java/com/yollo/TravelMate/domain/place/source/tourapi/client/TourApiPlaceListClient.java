package com.yollo.TravelMate.domain.place.source.tourapi.client;

import java.util.List;

import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourApiFailureReason;

import lombok.RequiredArgsConstructor;

@Component
@RequiredArgsConstructor
public class TourApiPlaceListClient {

    private final TourApiResponseClient responseClient;
    private final TourApiUrlBuilder urlBuilder;

    public TourApiListPage fetchPage(
            String areaCode,
            String contentTypeId,
            int numOfRows,
            int pageNo
    ) {
        return fetchPage(
                urlBuilder.areaBasedList(areaCode, contentTypeId, numOfRows, pageNo),
                numOfRows,
                pageNo
        );
    }

    public TourApiListPage fetchPage(
            String areaCode,
            String sigunguCode,
            String contentTypeId,
            int numOfRows,
            int pageNo
    ) {
        return fetchPage(
                urlBuilder.areaBasedList(areaCode, sigunguCode, contentTypeId, numOfRows, pageNo),
                numOfRows,
                pageNo
        );
    }

    private TourApiListPage fetchPage(
            String url,
            int numOfRows,
            int pageNo
    ) {
        var page = responseClient.fetch(url);
        long expectedSize = Math.min(numOfRows, Math.max(0L, page.totalCount() - ((long) pageNo - 1) * numOfRows));
        if (page.items().size() != expectedSize) {
            throw TourApiCollectionException.builder()
                    .reason(TourApiFailureReason.INCONSISTENT_PAGE)
                    .rawResponse(page.rawResponse())
                    .build();
        }
        List<TourApiListItem> items;
        try {
            items = page.items().stream().map(TourApiPlaceListClient::toListItem).toList();
        } catch (IllegalArgumentException exception) {
            throw TourApiCollectionException.builder()
                    .reason(TourApiFailureReason.INVALID_RESPONSE)
                    .rawResponse(page.rawResponse())
                    .cause(exception)
                    .build();
        }
        return new TourApiListPage(items, page.totalCount(), pageNo);
    }

    /** static - 스테이징된 raw JSON을 인덱싱할 때도 동일한 변환 규칙을 재사용합니다. */
    public static TourApiListItem toListItem(JsonNode node) {
        if (!node.isObject() || !node.path("contentid").isTextual()
                || node.path("contentid").asText().isBlank()) {
            throw new IllegalArgumentException("TourAPI 목록 항목에 유효한 contentid가 필요합니다.");
        }
        return new TourApiListItem(
                node.path("contentid").asText(null),
                node.path("contenttypeid").asText(null),
                node.path("title").asText(null),
                blankToNull(node.path("addr1").asText(null)),
                blankToNull(node.path("firstimage").asText(null)),   // 이미지 없으면 빈 문자열 → null
                parseDouble(node.path("mapx").asText(null)),         // 경도
                parseDouble(node.path("mapy").asText(null)),         // 위도
                blankToNull(node.path("areacode").asText(null)),     // processRaw에서 TourAreaCode 역조회용
                blankToNull(node.path("sigungucode").asText(null)),
                blankToNull(node.path("lclsSystm1").asText(null)),
                blankToNull(node.path("lclsSystm2").asText(null)),   // 신분류체계 중분류
                blankToNull(node.path("lclsSystm3").asText(null)),   // 신분류체계 소분류
                node.toString()                                      // raw JSON (스테이징 저장용)
        );
    }

    private static String blankToNull(String source) {
        return (source == null || source.isBlank()) ? null : source.trim();
    }

    private static Double parseDouble(String source) {
        if (source == null || source.isBlank()) {
            return null;
        }
        return Double.parseDouble(source.trim());
    }

    public record TourApiListItem(
            String contentId,
            String contentTypeId,
            String title,
            String addr1,
            String imageUrl,
            Double mapX,        // 경도(longitude)
            Double mapY,        // 위도(latitude)
            String areaCode,
            String sigunguCode,
            String lclsSystm1,
            String lclsSystm2,
            String lclsSystm3,
            String rawJson      // areaBasedList2 item 원본 JSON
    ) {}

    public record TourApiListPage(
            List<TourApiListItem> items,
            int totalCount,
            int pageNo
    ) {}
}
