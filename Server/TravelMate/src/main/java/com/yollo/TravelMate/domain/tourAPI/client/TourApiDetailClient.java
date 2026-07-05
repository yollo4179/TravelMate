package com.yollo.TravelMate.domain.tourAPI.client;
 
 
import java.util.ArrayList;
import java.util.List;
 
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
 
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.tourAPI.urlBuilder.TourApiUrlBuilder;
import com.yollo.TravelMate.util.UrlUtil;
 
//디테일 클라이언트
@Component
public class TourApiDetailClient {
 
    private static final int INFO_MAX_ROWS = 100;  // 반복정보 최대 수집 개수
    private static final Logger log = LoggerFactory.getLogger(TourApiDetailClient.class);
 
    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final TourApiUrlBuilder urlBuilder;
 
    // RestClient는 이 클라이언트 전용으로 생성 (Kakao 등 다른 RestClient 빈과 설정이 섞이지 않도록 분리)
    public TourApiDetailClient(ObjectMapper objectMapper, TourApiUrlBuilder urlBuilder) {
        this.restClient = RestClient.create();
        this.objectMapper = objectMapper;
        this.urlBuilder = urlBuilder;
    }
 
    public record TourApiCommonResult(
            String overview,
            String homepageUrl,
            String firstImage
    ) {}

    public TourApiCommonResult fetchCommon(String contentId) {
        String url = urlBuilder.detailCommon(contentId);
        try {
            String rawResponse = restClient.get().uri(url).retrieve().body(String.class);
            JsonNode item = extractFirstItem(rawResponse);
            if (item == null) {
                return new TourApiCommonResult(null, null, null);
            }
            String overview = blankToNull(item.path("overview").asText(null));
            String homepage = UrlUtil.extractHomepageUrl(item.path("homepage").asText(null));
            String image = blankToNull(item.path("firstimage").asText(null));
            return new TourApiCommonResult(overview, homepage, image);
        } catch (Exception e) {
            log.error("detailCommon2 호출 실패: contentId={}", contentId, e);
            return new TourApiCommonResult(null, null, null);
        }
    }

    private String blankToNull(String s) {
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
 
    /** detailInfo1 - 반복정보(체험 프로그램 등). 실패 시 빈 리스트. */
    public List<TourApiInfoItem> fetchInfoItems(String contentId, String contentTypeId) {
        String url = urlBuilder.detail("/detailInfo2", contentId, contentTypeId, INFO_MAX_ROWS);
        List<TourApiInfoItem> items = new ArrayList<>();
 
        try {
            String rawResponse = restClient.get()
                    .uri(url)
                    .retrieve()
                    .body(String.class);
            JsonNode itemNode = objectMapper.readTree(rawResponse)
                    .path("response")
                    .path("body")
                    .path("items")
                    .path("item");
 
            if (itemNode.isArray()) {
                for (JsonNode node : itemNode) {
                    items.add(toInfoItem(node));
                }
            } else if (itemNode.isObject() && !itemNode.isMissingNode()) {
                items.add(toInfoItem(itemNode));
            }
        } catch (Exception e) {
            log.error("detailInfo2 호출/파싱 실패: contentId={}, contentTypeId={}", contentId, contentTypeId, e);
            return List.of();
        }
 
        return items;
    }
 
    private TourApiInfoItem toInfoItem(JsonNode node) {
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
}