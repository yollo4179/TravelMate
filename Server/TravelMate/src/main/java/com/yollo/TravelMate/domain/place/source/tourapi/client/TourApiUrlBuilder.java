package com.yollo.TravelMate.domain.place.source.tourapi.client;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * TourAPI URL 빌더.
 * 공통 파라미터(serviceKey, MobileOS, MobileApp, _type)를 한 곳에서 관리하고,
 * 각 API 엔드포인트별 URL 생성을 담당한다.
 *
 * 주의: UriComponentsBuilder는 가변 객체이므로 매 호출마다 새 인스턴스를 만든다.
 * (필드로 공유하면 파라미터가 누적되어 URL이 오염된다)
 * - 각각의 빌더를 쪼개서 클래스로 관리하는것 고려( 성능 이슈 크게 없다면 그냥 매번 재빌드ㄱㄱ)
 */

@Component
public class TourApiUrlBuilder {

    // 발급 키가 KorService2 전용이므로 base와 모든 엔드포인트를 2로 맞춘다.
    private static final String BASE_URL = "https://apis.data.go.kr/B551011/KorService2";

    private final String serviceKey;

    public TourApiUrlBuilder(@Value("${tourapi.service-key}") String serviceKey) {
        this.serviceKey = serviceKey;
    }

    /** 공통 파라미터가 채워진 새 빌더 반환 */
    private UriComponentsBuilder base(String path) {
        return UriComponentsBuilder.fromUriString(BASE_URL + path)
                .queryParam("serviceKey", serviceKey)
                .queryParam("MobileOS", "ETC")
                .queryParam("MobileApp", "TravelMate")
                .queryParam("_type", "json");
    }

    /** detailIntro2 / detailInfo2 공통 (contentId + contentTypeId 기반). pageNo 기본값 1. */
    public String detail(String path, String contentId, String contentTypeId, int numOfRows) {
        return detail(path, contentId, contentTypeId, numOfRows, 1);
    }

    /** detailInfo2처럼 결과가 100건을 넘어 페이지를 넘겨야 할 때 사용. */
    public String detail(String path, String contentId, String contentTypeId, int numOfRows, int pageNo) {
        String url = base(path)
            .queryParam("contentId", contentId)
            .queryParam("contentTypeId", contentTypeId)
            .queryParam("numOfRows", numOfRows)
            .queryParam("pageNo", pageNo)
            .build(true)
            .toUriString();

        System.out.println("detailInfo2 TourAPI URL: " + url);  // 임시
        return url;
    }

    /** detailCommon2 (overview 개요 조회) */
    public String detailCommon(String contentId) {
        String url = base("/detailCommon2")
                .queryParam("contentId", contentId)
                .queryParam("numOfRows", 1)
                .queryParam("pageNo", 1)
                .build(true)
                .toUriString();

        System.out.println("detailCommon2 TourAPI URL: " + url);  // 임시

        return url;
    }

    /** areaBasedList2 지역기반 목록 조회 URL을 생성합니다. */
    public String areaBasedList(String areaCode, String contentTypeId, int numOfRows, int pageNo) {
        return base("/areaBasedList2")
                .queryParam("areaCode", areaCode)
                .queryParam("contentTypeId", contentTypeId)
                .queryParam("arrange", "A")   // A: 제목순
                .queryParam("numOfRows", numOfRows)
                .queryParam("pageNo", pageNo)
                .build(true)
                .toUriString();
    }

    /** areaBasedList2 오버로드 - 시군구코드(sigunguCode)까지 넣어서 세부지역까지 검색 */
    public String areaBasedList(String areaCode, String sigunguCode, String contentTypeId, int numOfRows, int pageNo) {
        return base("/areaBasedList2")
                .queryParam("areaCode", areaCode)
                .queryParam("sigunguCode", sigunguCode)
                .queryParam("contentTypeId", contentTypeId)
                .queryParam("arrange", "A")   // A: 제목순
                .queryParam("numOfRows", numOfRows)
                .queryParam("pageNo", pageNo)
                .build(true)
                .toUriString();
    }
}

