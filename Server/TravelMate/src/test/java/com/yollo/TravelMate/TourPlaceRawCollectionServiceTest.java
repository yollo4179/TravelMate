package com.yollo.TravelMate;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import com.yollo.TravelMate.domain.place.source.tourapi.code.TourAreaCode;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceRawCollectionService;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceRawCollectionService.CollectRawResult;

/**
 * 1단계(raw 수집)만 단독으로 확인하는 테스트.
 * TourAPI를 호출해서 tour_api_raw에 원본 JSON이 제대로 쌓이는지만 본다.
 * 임베딩/places 적재는 하지 않으므로 임베딩 서버가 안 떠있어도 실행 가능하다.
 */
@SpringBootTest
class TourPlaceRawCollectionServiceTest {

    @Autowired
    TourPlaceRawCollectionService rawCollector;

    @Autowired
    JdbcTemplate jdbc;

    @Test
    void 서울_관광지_raw수집() {
        CollectRawResult result = rawCollector.collectRaw(
                List.of(TourAreaCode.서울),
                List.of(TourContentType.관광지));

        System.out.println("=== raw 수집 결과 ===");
        System.out.println("검색: " + result.searched());
        System.out.println("raw 저장: " + result.saved());
        System.out.println("스킵(이미 존재): " + result.skipped());

        // --- 저장 검증 ---
        Integer rawCount = jdbc.queryForObject(
                "select count(*) from tour_api_raw where tour_content_type_id = ?",
                Integer.class, TourContentType.관광지.getContentTypeId());
        System.out.println("tour_api_raw(관광지) 총 건수: " + rawCount);

        Integer unprocessedCount = jdbc.queryForObject(
                "select count(*) from tour_api_raw where processed_at is null", Integer.class);
        System.out.println("미처리(processed_at is null) 건수: " + unprocessedCount);

        // --- raw_list/raw_common이 실제로 채워졌는지 샘플 확인 ---
        jdbc.query("""
                select tour_content_id,
                       raw_list ->> 'title' as title,
                       raw_common ->> 'overview' is not null as has_overview,
                       jsonb_array_length(coalesce(raw_info, '[]'::jsonb)) as info_count
                from tour_api_raw
                where tour_content_type_id = ?
                order by fetched_at
                limit 5
                """, ps -> ps.setString(1, TourContentType.관광지.getContentTypeId()), rs -> {
            System.out.printf("- %s | %s | overview=%s | info건수=%d%n",
                    rs.getString("tour_content_id"), rs.getString("title"),
                    rs.getBoolean("has_overview"), rs.getInt("info_count"));
        });
    }
}
