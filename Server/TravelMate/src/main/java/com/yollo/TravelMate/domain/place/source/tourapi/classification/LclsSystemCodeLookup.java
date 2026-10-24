package com.yollo.TravelMate.domain.place.source.tourapi.classification;

import java.io.IOException;
import java.io.InputStream;
import java.util.Map;

import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * TourAPI 신분류체계(lclsSystm1/2/3) 코드 → 이름 사전.
 * 한국관광공사 "신분류체계정보 관광타입정보 연계 정의서" 엑셀에서 추출한 고정 테이블을
 * 리소스(tourapi/lcls-systm-codes.json)로 번들링해서 쓴다.
 * lclsSystmCode2 API를 매 장소마다 부르는 건 낭비라서(코드 자체는 안 바뀌는 고정 사전),
 * 애초에 라이브 조회 없이 정적 테이블로 들고 있는다.
 */
@Component
public class LclsSystemCodeLookup {

    private final Map<String, String> level1;
    private final Map<String, String> level2;
    private final Map<String, String> level3;

    @SuppressWarnings("unchecked")
    public LclsSystemCodeLookup(ObjectMapper objectMapper) {
        try (InputStream json = new ClassPathResource("tourapi/lcls-systm-codes.json").getInputStream()) {
            Map<String, Object> levels = objectMapper.readValue(json, Map.class);
            this.level1 = (Map<String, String>) levels.get("lclsSystm1");
            this.level2 = (Map<String, String>) levels.get("lclsSystm2");
            this.level3 = (Map<String, String>) levels.get("lclsSystm3");
        } catch (IOException e) {
            throw new IllegalStateException("lcls-systm-codes.json 로드 실패", e);
        }
    }

    /** 소분류명 → 없으면 중분류명 → 없으면 대분류명 → 다 없으면 null. */
    public String resolveName(String lclsSystm1, String lclsSystm2, String lclsSystm3) {
        if (lclsSystm3 != null && level3.containsKey(lclsSystm3)) {
            return level3.get(lclsSystm3);
        }
        if (lclsSystm2 != null && level2.containsKey(lclsSystm2)) {
            return level2.get(lclsSystm2);
        }
        if (lclsSystm1 != null && level1.containsKey(lclsSystm1)) {
            return level1.get(lclsSystm1);
        }
        return null;
    }
}
