package com.yollo.TravelMate;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import com.yollo.TravelMate.domain.place.enums.RegionData;
import com.yollo.TravelMate.domain.place.service.PlaceCollectorService;

@SpringBootTest
public class PlaceCollectorTest {

    @Autowired
    private PlaceCollectorService collector;

    @Test
    void 소규모_수집_서울_가평() {
        var result = collector.collectAll(List.of(
                RegionData.City.서울, RegionData.City.가평));

        System.out.println("검색 횟수: " + result.searched());
        System.out.println("적재: " + result.inserted());
        System.out.println("중복 스킵: " + result.skippedDup());
        System.out.println("지역 불일치 스킵: " + result.skippedRegion());
    }
}
