package com.yollo.TravelMate.domain.place.service;


import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.domain.place.data.response.KakaoPlaceResponseDto;

import java.util.List;

/**
 * 카카오 로컬 API 호출을 감싸는 서비스.
 *
 * @Cacheable로 동일 키워드 재검색 시 카카오 API를 다시 호출하지 않고
 * Redis에 저장된 결과를 즉시 반환한다. (캐시 키: "place:search:{query}")
 *
 * 이 부분이 "외부 API 호출 비용/속도를 캐싱으로 얼마나 줄였는지"를
 * 수치(캐시 히트율, 평균 응답시간 비교)로 설명할 수 있는 지점이다.
 */
@Service
public class PlaceSearchService {

    private final KakaoLocalService kakaoLocalService;

    public PlaceSearchService(KakaoLocalService kakaoLocalService) {
        this.kakaoLocalService = kakaoLocalService;
    }

    @Cacheable(cacheNames = "placeSearch", key = "#query")
    public List<KakaoPlaceResponseDto> search(String query) {
        return kakaoLocalService.searchByKeyword(query);
    }
}
