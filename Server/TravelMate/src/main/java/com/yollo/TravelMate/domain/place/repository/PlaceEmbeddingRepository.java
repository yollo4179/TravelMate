package com.yollo.TravelMate.domain.place.repository;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.yollo.TravelMate.domain.place.data.internal.PlaceEmbeddingTarget;
import com.yollo.TravelMate.domain.place.data.internal.PlaceEmbeddingUpdate;
import com.yollo.TravelMate.util.VectorUtil;

@Repository
public class PlaceEmbeddingRepository {

    private static final Logger log = LoggerFactory.getLogger(PlaceEmbeddingRepository.class);

    private final JdbcTemplate jdbcTemplate;

    public PlaceEmbeddingRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<PlaceEmbeddingTarget> findTargets(long afterId, int limit) {
        String sql = """
                select id, name, description
                from places
                where id > ?
                  and tour_content_id is not null
                order by id
                limit ?
                """;
        return jdbcTemplate.query(
                sql,
                (resultSet, rowNumber) -> new PlaceEmbeddingTarget(
                        resultSet.getLong("id"),
                        resultSet.getString("name"),
                        resultSet.getString("description")
                ),
                afterId,
                limit
        );
    }

    public void updateAll(List<PlaceEmbeddingUpdate> updates) {
        List<PlaceEmbeddingUpdate> validUpdates = updates.stream()
                .filter(update -> update.embedding() != null)
                .toList();
        updates.stream()
                .filter(update -> update.embedding() == null)
                .forEach(update -> log.warn(
                        "재임베딩 결과가 null이라 업데이트를 건너뜁니다: placeId={}",
                        update.id()
                ));

        if (validUpdates.isEmpty()) {
            return;
        }

        String sql = "update places set embedding = ?::vector where id = ?";
        jdbcTemplate.batchUpdate(
                sql,
                validUpdates,
                validUpdates.size(),
                (preparedStatement, update) -> {
                    preparedStatement.setString(1, VectorUtil.toVectorString(update.embedding()));
                    preparedStatement.setLong(2, update.id());
                }
        );
    }
}
