package com.yollo.TravelMate.domain.tourAPI.repository;


import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class PlaceDetailRepository {

    private final JdbcTemplate jdbc;

    public PlaceDetailRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** detailIntro1 raw json upsert. rawIntroJson이 null이면 호출하지 마세요(호출부에서 체크). */
    public void upsertIntro(Long placeId, String rawIntroJson) {
        String sql = """
                insert into place_details (place_id, raw_intro, fetched_at)
                values (?, ?::jsonb, now())
                on conflict (place_id) do update
                set raw_intro = excluded.raw_intro, fetched_at = now()
                """;
        jdbc.update(sql, placeId, rawIntroJson);
    }

    /** detailInfo1 반복정보 재적재. 기존 것 지우고 새로 채움 (앞서 pin_activities와 동일한 정책). */
    public void replaceProgramItems(Long placeId, List<ProgramInsert> items) {
        jdbc.update("delete from place_programs where place_id = ?", placeId);

        if (items.isEmpty()) {
            return;
        }

        String sql = """
                insert into place_programs (place_id, info_name, info_text, serial_num, fetched_at)
                values (?, ?, ?, ?, now())
                """;
        jdbc.batchUpdate(sql, items, items.size(), (ps, item) -> {
            ps.setLong(1, placeId);
            ps.setString(2, item.infoName());
            ps.setString(3, item.infoText());
            ps.setString(4, item.serialNum());
        });
    }

    public List<ProgramInsert> findProgramsByPlaceId(Long placeId) {
        String sql = """
                select info_name, info_text, serial_num
                from place_programs
                where place_id = ?
                order by program_id
                """;
        return jdbc.query(sql, (rs, n) -> new ProgramInsert(
                rs.getString("info_name"),
                rs.getString("info_text"),
                rs.getString("serial_num")
        ), placeId);
    }

    /** raw_intro는 JSONB이므로 텍스트로 캐스팅해서 반환. 없으면 null. */
    public String findRawIntroByPlaceId(Long placeId) {
        String sql = "select raw_intro::text from place_details where place_id = ?";
        List<String> result = jdbc.query(sql, (rs, n) -> rs.getString(1), placeId);
        return result.isEmpty() ? null : result.get(0);
    }

    public boolean existsByPlaceId(Long placeId) {
        Integer cnt = jdbc.queryForObject(
                "select count(*) from place_details where place_id = ?",
                Integer.class, placeId);
        return cnt != null && cnt > 0;
    }

    public record ProgramInsert(String infoName, String infoText, String serialNum) {}
}