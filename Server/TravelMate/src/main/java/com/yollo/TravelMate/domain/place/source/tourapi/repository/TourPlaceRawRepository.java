package com.yollo.TravelMate.domain.place.source.tourapi.repository;

import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * TourAPI 원본 JSON 스테이징 저장소.
 * 1단계(수집)에서 여기 저장만 하고, 2단계(가공)에서 processed_at이 null인 행을 읽어
 * description 조립 + 임베딩 + places 적재를 한다. TourAPI 일일 쿼터가 제한적이라
 * 가공 로직을 바꿀 때마다 재수집하지 않도록 분리했다.
 */
@Repository
public class TourPlaceRawRepository {

    private final JdbcTemplate jdbc;

    public TourPlaceRawRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public boolean exists(String tourContentId) {
        Integer cnt = jdbc.queryForObject(
                "select count(*) from tour_api_raw where tour_content_id = ?",
                Integer.class, tourContentId);
        return cnt != null && cnt > 0;
    }

    /** rawList/rawCommon/rawInfo는 JSON 문자열(또는 null). null이면 NULL로 저장. */
    public void upsert(String tourContentId, String tourContentTypeId,
                        String rawList, String rawCommon, String rawInfo) {
        String sql = """
                insert into tour_api_raw (tour_content_id, tour_content_type_id, raw_list, raw_common, raw_info, fetched_at)
                values (?, ?, ?::jsonb, ?::jsonb, ?::jsonb, now())
                on conflict (tour_content_id) do update
                set raw_list = excluded.raw_list,
                    raw_common = excluded.raw_common,
                    raw_info = excluded.raw_info,
                    fetched_at = now()
                """;
        jdbc.update(sql, tourContentId, tourContentTypeId, rawList, rawCommon, rawInfo);
    }

    public List<RawRow> findUnprocessed(int limit) {
        String sql = """
                select tour_content_id, tour_content_type_id,
                       raw_list::text as raw_list, raw_common::text as raw_common, raw_info::text as raw_info
                from tour_api_raw
                where processed_at is null
                order by fetched_at
                limit ?
                """;
        return jdbc.query(sql, (rs, n) -> new RawRow(
                rs.getString("tour_content_id"),
                rs.getString("tour_content_type_id"),
                rs.getString("raw_list"),
                rs.getString("raw_common"),
                rs.getString("raw_info")
        ), limit);
    }

    public void markProcessed(String tourContentId) {
        jdbc.update("update tour_api_raw set processed_at = now() where tour_content_id = ?", tourContentId);
    }

    public record RawRow(
            String tourContentId,
            String tourContentTypeId,
            String rawList,
            String rawCommon,
            String rawInfo
    ) {}
}
