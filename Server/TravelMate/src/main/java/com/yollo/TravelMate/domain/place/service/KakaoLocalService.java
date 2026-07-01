package com.yollo.TravelMate.domain.place.service;


import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.RequestEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import com.yollo.TravelMate.domain.place.data.external.KakaoLocalExternalDto;
import com.yollo.TravelMate.domain.place.data.response.KakaoPlaceResponseDto;

import java.net.URI;
import java.util.List;

/**
 * 카카오 로컬 API(키워드 장소 검색) 연동 서비스.
 * REST API 키는 서버에만 보관하고, 안드로이드는 이 서비스가 노출하는
 * /api/places/search 엔드포인트만 호출한다.
 */
@Service
public class KakaoLocalService {

    private final RestClient restClient;

    @Value("${kakao.rest-api-key}")
    private String kakaoRestApiKey;

    public KakaoLocalService(RestClient.Builder builder) {
        this.restClient = builder.baseUrl("https://dapi.kakao.com").build();
    }

    /**
     * 키워드로 장소를 검색한다.
     * 예: GET /v2/local/search/keyword.json?query=경복궁
     */
    public List<KakaoPlaceResponseDto> searchByKeyword(String keyword) {
    	KakaoLocalExternalDto response = restClient.get()
                .uri(uriBuilder -> uriBuilder
                        .path("/v2/local/search/keyword.json")
                        .queryParam("query", keyword)
                        .queryParam("size", 15)
                        .build())
                .header(HttpHeaders.AUTHORIZATION, "KakaoAK " + kakaoRestApiKey)
                .retrieve()
                .body(KakaoLocalExternalDto.class);

        return response == null ? List.of() : response.toDtoList();
    }
}
