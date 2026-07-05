package com.yollo.TravelMate.domain.tourAPI.client;
 
 
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
 
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
 
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.tourAPI.urlBuilder.TourApiUrlBuilder;
import com.yollo.TravelMate.util.UrlUtil;
 
/**
 * TourAPI 지역기반 목록 조회(areaBasedList1) 클라이언트.
 * 한 페이지 결과를 items + totalCount + pageNo로 감싼 TourApiListPage로 반환한다.
 * Collector는 totalCount를 보고 총 페이지 수를 계산해 페이징 루프를 돈다.
 */
@Component
public class TourApiListClient {
 
    private static final Logger log = LoggerFactory.getLogger(TourApiListClient.class);
    private static final Pattern HREF_PATTERN = Pattern.compile("href=\"([^\"]+)\"");
 
    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final TourApiUrlBuilder urlBuilder;
 
    // RestClient는 이 클라이언트 전용으로 생성 (Kakao 등 다른 RestClient 빈과 설정이 섞이지 않도록 분리)
    public TourApiListClient(ObjectMapper objectMapper, TourApiUrlBuilder urlBuilder) {
        this.restClient = RestClient.create();
        this.objectMapper = objectMapper;
        this.urlBuilder = urlBuilder;
    }
 
    /**
     * 특정 지역·타입의 한 페이지를 조회한다.
     * 실패하거나 결과가 없으면 빈 페이지(items 비어있음, totalCount 0)를 반환한다.
     */
    public TourApiListPage fetchPage(
    		String areaCode,
    		String contentTypeId, 
    		int numOfRows,
    		int pageNo) {
        
    	
    	String url = urlBuilder.areaBasedList(areaCode, contentTypeId, numOfRows, pageNo);
        List<TourApiListItem> items = new ArrayList<>();
        int totalCount = 0;
 
        try {
            String rawResponse = restClient.get()
                    .uri(url)
                    .retrieve()
                    .body(String.class);
            JsonNode body = objectMapper.readTree(rawResponse)
                    .path("response").path("body");
 
            totalCount = body.path("totalCount").asInt(0);
 
            JsonNode itemNode = body.path("items").path("item");
            if (itemNode.isArray()) {
                for (JsonNode node : itemNode) {
                    items.add(toListItem(node));
                }
            } else if (itemNode.isObject() && !itemNode.isMissingNode()) {
                items.add(toListItem(itemNode));
            }
        } catch (Exception e) {
            log.error("areaBasedList1 호출/파싱 실패: areaCode={}, contentTypeId={}, pageNo={}",
                    areaCode, contentTypeId, pageNo, e);
            return new TourApiListPage(List.of(), 0, pageNo);
        }
 
        return new TourApiListPage(items, totalCount, pageNo);
    }
 
    private TourApiListItem toListItem(JsonNode node) {
        return new TourApiListItem(
                node.path("contentid").asText(null),
                node.path("contenttypeid").asText(null),
                node.path("title").asText(null),
                blankToNull(node.path("addr1").asText(null)),
                blankToNull(node.path("firstimage").asText(null)),   // 이미지 없으면 빈 문자열 → null
                parseDouble(node.path("mapx").asText(null)),         // 경도
                parseDouble(node.path("mapy").asText(null))          // 위도
        );
    }
 
    /** homepage 필드는 <a href="URL">텍스트</a> 형태 → href 값(순수 URL)만 추출. 없으면 null. */
    
 
    private String blankToNull(String s) {
        return (s == null || s.isBlank()) ? null : s.trim();
    }
 
    private Double parseDouble(String s) {
        if (s == null || s.isBlank()) {
            return null;
        }
        try {
            return Double.parseDouble(s.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
 
    public record TourApiListItem(
            String contentId,
            String contentTypeId,
            String title,
            String addr1,
            String imageUrl,
            Double mapX,   // 경도(longitude)
            Double mapY    // 위도(latitude)
    ) {}
 
    public record TourApiListPage(
            List<TourApiListItem> items,
            int totalCount,
            int pageNo
    ) {}
}