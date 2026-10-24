package com.yollo.TravelMate.domain.place.source.tourapi.client;
 
 
import java.util.ArrayList;
import java.util.List;
 
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
 
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.util.UrlUtil;
 
//디테일 클라이언트
@Component
public class TourApiPlaceDetailClient {
 
    private static final int INFO_MAX_ROWS = 100;  // 반복정보 최대 수집 개수
    private static final Logger log = LoggerFactory.getLogger(TourApiPlaceDetailClient.class);
 
    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final TourApiUrlBuilder urlBuilder;
 
    // RestClient는 이 클라이언트 전용으로 생성 (Kakao 등 다른 RestClient 빈과 설정이 섞이지 않도록 분리)
    public TourApiPlaceDetailClient(ObjectMapper objectMapper, TourApiUrlBuilder urlBuilder) {
        this.restClient = RestClient.create();
        this.objectMapper = objectMapper;
        this.urlBuilder = urlBuilder;
    }
 
    public record TourApiCommonResult(
            String overview,
            String homepageUrl,
            String firstImage,
            String rawJson   // detailCommon2 item 원본 JSON (스테이징 저장용, 못 찾으면 null)
    ) {}

    public TourApiCommonResult fetchCommon(String contentId) {
        String url = urlBuilder.detailCommon(contentId);
        try {
            String rawResponse = restClient.get().uri(url).retrieve().body(String.class);
            JsonNode item = extractFirstItem(rawResponse);
            if (item == null) {
                return new TourApiCommonResult(null, null, null, null);
            }
            return toCommonResult(item);
        } catch (Exception e) {
            log.error("detailCommon2 호출 실패: contentId={}", contentId, e);
            return new TourApiCommonResult(null, null, null, null);
        }
    }

    /** static - 스테이징된 raw JSON을 인덱싱할 때도 동일한 변환 규칙을 재사용합니다. */
    public static TourApiCommonResult toCommonResult(JsonNode item) {
        String overview = blankToNull(item.path("overview").asText(null));
        String homepage = UrlUtil.extractHomepageUrl(item.path("homepage").asText(null));
        String image = blankToNull(item.path("firstimage").asText(null));
        return new TourApiCommonResult(overview, homepage, image, item.toString());
    }

    private static String blankToNull(String s) {
        return (s == null || s.isBlank()) ? null : s.trim();
    }
 
    /** detailIntro1 - contentTypeId별 필드가 달라 raw JSON 그대로 반환. 실패 시 null. */
    public TourApiIntroResult fetchIntro(String contentId, String contentTypeId) {
        String url = urlBuilder.detail("/detailIntro2", contentId, contentTypeId, 1);
 
        try {
            String rawResponse = restClient.get()
                    .uri(url)
                    .retrieve()
                    .body(String.class);
            JsonNode item = extractFirstItem(rawResponse);
            if (item == null) {
                log.warn("detailIntro1 응답에 item이 없습니다: contentId={}, contentTypeId={}", contentId, contentTypeId);
                return new TourApiIntroResult(contentId, null);
            }
            return new TourApiIntroResult(contentId, item.toString());
        } catch (Exception e) {
            log.error("detailIntro1 호출 실패: contentId={}, contentTypeId={}", contentId, contentTypeId, e);
            return new TourApiIntroResult(contentId, null);
        }
    }
 
    /**
     * detailInfo1 - 반복정보(체험 프로그램 등). 실패 시 빈 리스트 + rawJson null.
     * totalCount가 INFO_MAX_ROWS(한 페이지)를 넘으면 나머지 페이지까지 이어서 가져온다
     * (안 그러면 100건 넘는 장소는 뒷부분이 조용히 누락됨).
     */
    public TourApiInfoResult fetchInfoItems(String contentId, String contentTypeId) {
        List<TourApiInfoItem> allItems = new ArrayList<>();
        List<JsonNode> allRawNodes = new ArrayList<>();
        int page = 1;

        try {
            while (true) {
                String url = urlBuilder.detail("/detailInfo2", contentId, contentTypeId, INFO_MAX_ROWS, page);
                String rawResponse = restClient.get().uri(url).retrieve().body(String.class);
                JsonNode body = objectMapper.readTree(rawResponse).path("response").path("body");
                int totalCount = body.path("totalCount").asInt(0);
                JsonNode itemNode = body.path("items").path("item");

                TourApiInfoResult pageResult = toInfoResult(itemNode);
                allItems.addAll(pageResult.items());
                if (itemNode.isArray()) {
                    itemNode.forEach(allRawNodes::add);
                } else if (itemNode.isObject() && !itemNode.isMissingNode()) {
                    allRawNodes.add(itemNode);
                }

                if (totalCount <= page * INFO_MAX_ROWS) {
                    break;
                }
                page++;
            }
        } catch (Exception e) {
            log.error("detailInfo2 호출/파싱 실패: contentId={}, contentTypeId={}, page={}", contentId, contentTypeId, page, e);
            return new TourApiInfoResult(List.of(), null);
        }

        if (allRawNodes.isEmpty()) {
            return new TourApiInfoResult(List.of(), null);
        }
        var combined = objectMapper.createArrayNode();
        allRawNodes.forEach(combined::add);
        return new TourApiInfoResult(allItems, combined.toString());
    }

    /** static - raw JSON(detailInfo2의 items.item)을 재파싱하는 processRaw 단계에서도 그대로 재사용. */
    public static TourApiInfoResult toInfoResult(JsonNode itemNode) {
        List<TourApiInfoItem> items = new ArrayList<>();
        if (itemNode.isArray()) {
            for (JsonNode node : itemNode) {
                items.add(toInfoItem(node));
            }
        } else if (itemNode.isObject() && !itemNode.isMissingNode()) {
            items.add(toInfoItem(itemNode));
        }
        String rawJson = items.isEmpty() ? null : itemNode.toString();
        return new TourApiInfoResult(items, rawJson);
    }

    public static TourApiInfoItem toInfoItem(JsonNode node) {
        return new TourApiInfoItem(
                node.path("infoname").asText(null),
                node.path("infotext").asText(null),
                node.path("serialnum").asText(null)
        );
    }
 
    private JsonNode extractFirstItem(String rawResponse) {
        try {
            JsonNode itemNode = objectMapper.readTree(rawResponse)
                    .path("response")
                    .path("body")
                    .path("items")
                    .path("item");
            if (itemNode.isArray() && itemNode.size() > 0) {
                return itemNode.get(0);
            } else if (itemNode.isObject() && !itemNode.isMissingNode()) {
                return itemNode;
            }
        } catch (Exception e) {
            log.error("TourAPI 응답 파싱 실패", e);
        }
        return null;
    }
 
    public record TourApiIntroResult(
    		String tourContentId,
    		String rawIntroJson) 
    {}
 
    public record TourApiInfoItem(
        String infoName,
        String infoText,
        String serialNum
    ) {}

    public record TourApiInfoResult(
        List<TourApiInfoItem> items,
        String rawJson   // detailInfo2 items.item 원본 JSON (스테이징 저장용, 결과 없으면 null)
    ) {}
}
