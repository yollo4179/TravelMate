package com.yollo.TravelMate;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceIndexingService;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceIndexingService.ProcessResult;

/**
 * 2단계(가공)만 단독으로 확인하는 테스트.
 * TourAPI를 전혀 호출하지 않고 tour_api_raw에 이미 쌓인 미처리 행만 읽어서
 * description 조립 + 임베딩 + places 적재가 되는지 본다.
 * (그래서 TourPlaceRawCollectionServiceTest와 달리 쿼터를 전혀 쓰지 않는다 - 임베딩 서버만 떠있으면 됨)
 * tour_api_raw에 미처리 행이 없으면 read=0으로 끝나므로, 먼저 Collect Test를 한 번 돌려둬야 의미 있는 검증이 된다.
 */
@SpringBootTest
class TourPlaceIndexingServiceTest {

    @Autowired
    TourPlaceIndexingService processor;

    @Autowired
    JdbcTemplate jdbc;

    @Test
    void raw_가공() {
        Integer beforeUnprocessed = jdbc.queryForObject(
                "select count(*) from tour_api_raw where processed_at is null", Integer.class);
        System.out.println("가공 전 미처리 건수: " + beforeUnprocessed);

        ProcessResult result = processor.processRaw(500);

        System.out.println("=== 가공 결과 ===");
        System.out.println("조회 대상: " + result.read());
        System.out.println("인덱싱: " + result.indexed());
        System.out.println("overview 없어 임베딩 스킵: " + result.skippedWithoutOverview());
        System.out.println("파싱 실패로 스킵: " + result.skippedUnparseable());

        Integer afterUnprocessed = jdbc.queryForObject(
                "select count(*) from tour_api_raw where processed_at is null", Integer.class);
        System.out.println("가공 후 미처리 건수: " + afterUnprocessed);

        Integer placeCount = jdbc.queryForObject(
                "select count(*) from places where tour_content_id is not null", Integer.class);
        Integer embeddedCount = jdbc.queryForObject(
                "select count(*) from places where embedding is not null", Integer.class);
        Integer programCount = jdbc.queryForObject(
                "select count(*) from place_programs", Integer.class);
        System.out.println("places(TourAPI) 총 건수: " + placeCount);
        System.out.println("임베딩된 건수: " + embeddedCount);
        System.out.println("place_programs 총 건수: " + programCount);

        // --- description이 "카테고리. 오버뷰" 형식으로 잘 조립됐는지 샘플 확인 ---
        jdbc.query("""
                select name, category, left(description, 80) as desc_preview,
                       (embedding is not null) as has_emb
                from places
                where tour_content_id is not null
                order by id desc
                limit 5
                """, rs -> {
            System.out.printf("- %s [%s] emb=%s | %s%n",
                    rs.getString("name"), rs.getString("category"),
                    rs.getBoolean("has_emb"), rs.getString("desc_preview"));
        });
    }
}
