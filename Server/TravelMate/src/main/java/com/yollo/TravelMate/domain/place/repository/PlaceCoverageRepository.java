package com.yollo.TravelMate.domain.place.repository;

import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Distinct region and category values in places, read from the same table that search filters on. */
@Repository
@RequiredArgsConstructor
public class PlaceCoverageRepository {
    private final JdbcTemplate jdbc;

    public List<String> regions() {
        return jdbc.queryForList("SELECT DISTINCT region FROM places WHERE region IS NOT NULL ORDER BY region", String.class);
    }

    public List<String> categories() {
        return jdbc.queryForList("SELECT DISTINCT category FROM places WHERE category IS NOT NULL ORDER BY category", String.class);
    }
}
