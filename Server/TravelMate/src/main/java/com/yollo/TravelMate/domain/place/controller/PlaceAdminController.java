package com.yollo.TravelMate.domain.place.controller;

import java.util.List;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import com.yollo.TravelMate.domain.place.enums.RegionData;
import com.yollo.TravelMate.domain.place.service.PlaceCollectorService;
import com.yollo.TravelMate.domain.place.service.ReembeddingService;

import lombok.RequiredArgsConstructor;

@RestController
@RequiredArgsConstructor
public class PlaceAdminController {

    private final PlaceCollectorService collector;
    private final ReembeddingService reembedding;

    @PostMapping("/admin/places/collect")
    public PlaceCollectorService.CollectResult collectAll() {
        return collector.collectAll(null);
    }

    @PostMapping("/admin/places/collect/test")
    public PlaceCollectorService.CollectResult collectTest() {
        // 소규모 테스트: 도시 2개만
        return collector.collectAll(List.of(
                RegionData.City.서울, RegionData.City.가평));
    }

    @PostMapping("/admin/places/reembed")
    public String reembedAll() {
        int n = reembedding.reembedAll();
        return "재임베딩 완료: " + n + "건";
    }
    
   
    // 수도권만 먼저 (쿼터 분할)
    @PostMapping("/admin/places/collect/metro")
    public PlaceCollectorService.CollectResult collectMetro() {
        return collector.collectAll(List.of(
            RegionData.City.서울, RegionData.City.인천, RegionData.City.부평,
            RegionData.City.수원, RegionData.City.성남, RegionData.City.판교,
            RegionData.City.고양, RegionData.City.일산, RegionData.City.부천,
            RegionData.City.안산 
        ));
    }
}