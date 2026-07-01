package com.yollo.TravelMate.domain.place.data.external;


import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.yollo.TravelMate.domain.place.data.response.KakaoPlaceResponseDto;

import java.util.List;

/**
 * 카카오 로컬 API(키워드 검색) 응답 전체를 매핑하는 클래스.
 * 응답 형태: { "meta": {...}, "documents": [...] }
 * 우리가 실제로 쓰는 건 documents 배열뿐이라 meta는 무시(@JsonIgnoreProperties)한다.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public class KakaoLocalExternalDto {

    private List<Document> documents;

    public List<Document> getDocuments() {
        return documents;
    }

    public void setDocuments(List<Document> documents) {
        this.documents = documents;
    }

    /**
     * documents 배열의 개별 장소 항목을 그대로 받는 내부 클래스.
     * 카카오 응답 필드명이 snake_case라서 @JsonProperty로 매핑한다.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Document {

        @JsonProperty("place_name")
        private String placeName;

        @JsonProperty("road_address_name")
        private String roadAddressName;

        @JsonProperty("address_name")
        private String addressName;

        @JsonProperty("category_name")
        private String categoryName;

        @JsonProperty("x") // 경도(longitude)가 x로 내려온다
        private String x;

        @JsonProperty("y") // 위도(latitude)가 y로 내려온다
        private String y;

        @JsonProperty("id")
        private String id;

        public String getPlaceName() {
            return placeName;
        }

        public String getRoadAddressName() {
            return roadAddressName;
        }

        public String getAddressName() {
            return addressName;
        }

        public String getCategoryName() {
            return categoryName;
        }

        public String getX() {
            return x;
        }

        public String getY() {
            return y;
        }

        public String getId() {
            return id;
        }
    }

    /**
     * documents 리스트를 우리 서비스에서 쓰는 KakaoPlaceDto 리스트로 변환한다.
     * 카카오는 좌표를 문자열로 내려주므로 Double로 파싱이 필요하다.
     */
    public List<KakaoPlaceResponseDto> toDtoList() {
        if (documents == null) {
            return List.of();
        }
        return documents.stream()
                .map(doc -> new KakaoPlaceResponseDto(
                        doc.getPlaceName(),
                        Double.parseDouble(doc.getY()), // y = 위도
                        Double.parseDouble(doc.getX()), // x = 경도
                        doc.getRoadAddressName() != null ? doc.getRoadAddressName() : doc.getAddressName(),
                        doc.getCategoryName(),
                        doc.getId()
                ))
                .toList();
    }
}
