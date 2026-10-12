package com.yollo.TravelMate.domain.place.repository;

import java.util.ArrayList;
import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.util.VectorUtil;

@Repository
public class PlaceSemanticSearchRepository {

    private static final RowMapper<PlaceResult> PLACE_ROW_MAPPER =
            (resultSet, rowNumber) -> new PlaceResult(
                    resultSet.getLong("id"),
                    resultSet.getString("name"),
                    resultSet.getString("description"),
                    resultSet.getString("region"),
                    resultSet.getString("city"),
                    resultSet.getString("category"),
                    resultSet.getString("source_category"),
                    resultSet.getDouble("latitude"),
                    resultSet.getDouble("longitude"),
                    resultSet.getDouble("similarity"),
                    resultSet.getString("tour_content_id"),
                    resultSet.getString("image_url"),
                    resultSet.getString("homepage_url")
            );

    private final JdbcTemplate jdbcTemplate;

    public PlaceSemanticSearchRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<PlaceResult> searchSimilar(
            float[] queryEmbedding,
            String region,
            String city,
            String category,
            double minimumSimilarity,
            int limit
    ) {
        String vector = VectorUtil.toVectorString(queryEmbedding);
        StringBuilder sql = new StringBuilder("""
                select id, name, description, region, city, category, source_category,
                       latitude, longitude, tour_content_id, image_url, homepage_url,
                       1 - (embedding <=> ?::vector) as similarity
                from places
                where embedding is not null
                  and 1 - (embedding <=> ?::vector) >= ?
                """);
        List<Object> parameters = new ArrayList<>();
        parameters.add(vector);
        parameters.add(vector);
        parameters.add(minimumSimilarity);

        appendFilter(sql, parameters, "region", region);
        appendFilter(sql, parameters, "city", city);
        appendFilter(sql, parameters, "category", category);

        sql.append(" order by embedding <=> ?::vector limit ? ");
        parameters.add(vector);
        parameters.add(limit);

        return jdbcTemplate.query(
                sql.toString(),
                PLACE_ROW_MAPPER,
                parameters.toArray()
        );
    }

    private static void appendFilter(
            StringBuilder sql,
            List<Object> parameters,
            String column,
            String value
    ) {
        if (value == null || value.isBlank()) {
            return;
        }
        sql.append(" and ").append(column).append(" = ? ");
        parameters.add(value);
    }
}
