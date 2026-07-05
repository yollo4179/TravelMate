package com.yollo.TravelMate;



import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import com.yollo.TravelMate.domain.tourAPI.enums.TourAreaCode;
import com.yollo.TravelMate.domain.tourAPI.enums.TourContentType;
import com.yollo.TravelMate.domain.tourAPI.service.TourPlaceCollectorService;
import com.yollo.TravelMate.domain.tourAPI.service.TourPlaceCollectorService.CollectResult;

@SpringBootTest
class TourPlaceCollectorServiceTest {

    @Autowired
    TourPlaceCollectorService collector;

    @Autowired
    JdbcTemplate jdbc;

    /**
     * 1단계: 가장 작은 범위(서울 × 관광지)로 파이프라인 전체가 도는지 확인.
     * 여기서 검증할 것:
     *  - API 호출/파싱 정상 (좌표, 이미지, homepage)
     *  - 임베딩 서버 연동 정상
     *  - places / place_programs 저장 정상
     *  - 좌표가 뒤집히지 않았는지 (한국: 위도 33~38, 경도 124~132)
     */
    @Test
    void 서울_관광지_수집() {
        CollectResult result = collector.collectAll(
                List.of(TourAreaCode.서울),
                List.of(TourContentType.관광지));

        System.out.println("=== 수집 결과 ===");
        System.out.println("검색: " + result.searched());
        System.out.println("적재: " + result.inserted());
        System.out.println("overview 없어 임베딩 스킵: " + result.skippedNoOverview());

        // --- 저장 검증 ---
        Integer placeCount = jdbc.queryForObject(
                "select count(*) from places where tour_content_id is not null", Integer.class);
        System.out.println("places(TourAPI) 총 건수: " + placeCount);

        Integer embeddedCount = jdbc.queryForObject(
                "select count(*) from places where embedding is not null", Integer.class);
        System.out.println("임베딩된 건수: " + embeddedCount);

        Integer programCount = jdbc.queryForObject(
                "select count(*) from place_programs", Integer.class);
        System.out.println("place_programs 총 건수: " + programCount);

        // --- 좌표 정상 범위 검증 (뒤집힘 감지) ---
        Integer badCoords = jdbc.queryForObject("""
                select count(*) from places
                where tour_content_id is not null
                  and (latitude  not between 33 and 39
                    or longitude not between 124 and 132)
                  and latitude is not null
                """, Integer.class);
        System.out.println("좌표 이상치(범위 벗어남): " + badCoords);

        // --- 샘플 몇 건 눈으로 확인 ---
        jdbc.query("""
                select name, region, city, latitude, longitude,
                       (embedding is not null) as has_emb,
                       (image_url is not null) as has_img,
                       (homepage_url is not null) as has_home,
                       left(description, 60) as desc_preview
                from places
                where tour_content_id is not null
                order by id
                limit 5
                """, rs -> {
            System.out.printf("- %s | %s/%s | (%.4f, %.4f) | emb=%s img=%s home=%s | %s%n",
                    rs.getString("name"), rs.getString("region"), rs.getString("city"),
                    rs.getDouble("latitude"), rs.getDouble("longitude"),
                    rs.getBoolean("has_emb"), rs.getBoolean("has_img"), rs.getBoolean("has_home"),
                    rs.getString("desc_preview"));
        });
    }
}
