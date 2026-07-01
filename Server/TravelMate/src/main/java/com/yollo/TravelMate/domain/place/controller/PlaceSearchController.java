package com.yollo.TravelMate.domain.place.controller;


import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.yollo.TravelMate.domain.place.data.response.KakaoPlaceResponseDto;
import com.yollo.TravelMate.domain.place.service.PlaceSearchService;

import java.util.List;

@RestController
public class PlaceSearchController {

    private final PlaceSearchService placeSearchService;

    public PlaceSearchController(PlaceSearchService placeSearchService) {
        this.placeSearchService = placeSearchService;
    }

    /**
     * 안드로이드가 호출하는 단일 엔드포인트.
     * 내부적으로 Redis 캐시 확인 -> 없으면 카카오 로컬 API 호출 -> 캐싱 후 반환.
     *
     * GET /api/places/search?query=경복궁
     */
    @GetMapping("/api/places/search")
    public List<KakaoPlaceResponseDto> search(@RequestParam String query) {
        return placeSearchService.search(query);
    }
}
