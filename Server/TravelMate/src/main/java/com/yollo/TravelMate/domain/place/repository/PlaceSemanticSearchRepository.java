package com.yollo.TravelMate.domain.place.repository;

import java.util.ArrayList;
import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.config.observability.SearchTracing;
import com.yollo.TravelMate.util.VectorUtil;
import io.opentelemetry.api.trace.Span;

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
    private final SearchTracing searchTracing;

    public PlaceSemanticSearchRepository(JdbcTemplate jdbcTemplate, SearchTracing searchTracing) {
        this.jdbcTemplate = jdbcTemplate;
        this.searchTracing = searchTracing;
    }

    public List<PlaceResult> searchSimilar(
            float[] queryEmbedding,
            String region,
            String city,
            String category,
            double minimumSimilarity,
            int limit
    ) {
        return searchSimilar(queryEmbedding, region, city, category, minimumSimilarity, limit, null);
    }

    public List<PlaceResult> searchSimilar(
            float[] queryEmbedding,
            String region,
            String city,
            String category,
            double minimumSimilarity,
            int limit,
            com.yollo.TravelMate.domain.plan.data.request.PlanContext.Area area
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
        if (area != null) {
            // 범위를 먼저 적용해야 범위 밖 top-K가 안쪽 후보를 밀어내지 않는다.
            sql.append("""
                     AND latitude IS NOT NULL AND longitude IS NOT NULL
                     AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180
                     AND 6371000 * 2 * asin(sqrt(least(1.0,
                         power(sin(radians(latitude - ?) / 2), 2)
                         + cos(radians(?)) * cos(radians(latitude))
                         * power(sin(radians(longitude - ?) / 2), 2)))) <= ?
                    """);
            parameters.add(area.center().lat());
            parameters.add(area.center().lat());
            parameters.add(area.center().lon());
            parameters.add(area.radiusMeters());
        }

        sql.append(" order by embedding <=> ?::vector limit ? ");
        parameters.add(vector);
        parameters.add(limit);

        return searchTracing.trace("database.pgvector_search", () -> {
            Span.current().setAttribute("db.system", "postgresql");
            Span.current().setAttribute("db.operation.name", "SELECT");
            Span.current().setAttribute("db.collection.name", "places");
            Span.current().setAttribute("search.candidate_limit", limit);
            List<PlaceResult> results = jdbcTemplate.query(
                    sql.toString(),
                    PLACE_ROW_MAPPER,
                    parameters.toArray()
            );
            Span.current().setAttribute("search.candidate_count", results.size());
            return results;
        });
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
