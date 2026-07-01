package com.yollo.TravelMate.domain.place.data.response;
import java.util.List;

/**
 * 카카오 로컬 API 응답 매핑용 DTO.
 * 실제 응답 필드: documents[].place_name, x(경도), y(위도), road_address_name 등
 */
public record KakaoPlaceResponseDto(
        String placeName,
        double latitude,
        double longitude,
        String roadAddress,
        String categoryName,
        String kakaoPlaceId // 카카오 응답의 id 필드. 캐싱 시 중복 방지 키로 사용.
) {
}
