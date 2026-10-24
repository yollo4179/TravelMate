package com.yollo.TravelMate.domain.place.repository;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.yollo.TravelMate.domain.place.data.internal.PlaceCreateCommand;
import com.yollo.TravelMate.util.VectorUtil;

@Repository
public class PlaceCatalogRepository {

    private static final Logger log = LoggerFactory.getLogger(PlaceCatalogRepository.class);

    private final JdbcTemplate jdbcTemplate;

    public PlaceCatalogRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public boolean existsByTourContentId(String tourContentId) {
        Integer count = jdbcTemplate.queryForObject(
                "select count(*) from places where tour_content_id = ?",
                Integer.class,
                tourContentId
        );
        return count != null && count > 0;
    }

    public Long findIdByTourContentId(String tourContentId) {
        List<Long> placeIds = jdbcTemplate.query(
                "select id from places where tour_content_id = ?",
                (resultSet, rowNumber) -> resultSet.getLong("id"),
                tourContentId
        );
        return placeIds.isEmpty() ? null : placeIds.get(0);
    }

    public void insertBatch(List<PlaceCreateCommand> commands) {
        if (commands.isEmpty()) {
            return;
        }

        String sql = """
                insert into places (name, description, region, city, category, source_category,
                                    latitude, longitude, tour_content_id, tour_content_type_id,
                                    image_url, homepage_url, embedding)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::vector)
                on conflict (tour_content_id) do nothing
                """;

        jdbcTemplate.batchUpdate(
                sql,
                commands,
                commands.size(),
                (preparedStatement, command) -> {
                    preparedStatement.setString(1, command.name());
                    preparedStatement.setString(2, command.description());
                    preparedStatement.setString(3, command.region());
                    preparedStatement.setString(4, command.city());
                    preparedStatement.setString(5, command.category());
                    preparedStatement.setString(6, command.sourceCategory());
                    preparedStatement.setObject(7, command.latitude());
                    preparedStatement.setObject(8, command.longitude());
                    preparedStatement.setString(9, command.tourContentId());
                    preparedStatement.setString(10, command.tourContentTypeId());
                    preparedStatement.setString(11, command.imageUrl());
                    preparedStatement.setString(12, command.homepageUrl());
                    preparedStatement.setString(
                            13,
                            command.embedding() == null
                                    ? null
                                    : VectorUtil.toVectorString(command.embedding())
                    );
                    if (command.embedding() == null) {
                        log.warn(
                                "장소를 embedding 없이 저장합니다: tourContentId={}, name={}",
                                command.tourContentId(),
                                command.name()
                        );
                    }
                }
        );
    }
}
