package com.yollo.TravelMate.domain.place.repository;

import java.util.ArrayList;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.util.VectorUtil;

@Repository
public class PlaceVectorRepository {
 
	private static final Logger log = LoggerFactory.getLogger(PlaceVectorRepository.class);
 
	private final JdbcTemplate jdbc;
	
	public PlaceVectorRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }
	private static final RowMapper<PlaceResult> PLACE_ROW_MAPPER =
	        (rs, rowNum) -> new PlaceResult(
	                rs.getLong("id"),
	                rs.getString("name"),
	                rs.getString("description"),
	                rs.getString("region"),
	                rs.getString("city"),
	                rs.getString("category"),
	                rs.getString("source_category"),
	                rs.getDouble("latitude"),
	                rs.getDouble("longitude"),
	                rs.getDouble("similarity"),
	                rs.getString("tour_content_id"),
	                rs.getString("image_url"),
	                rs.getString("homepage_url"));
 
	
	public List<PlaceResult> searchSimilarTopK(float queryEmbedding[], int k) {
		
		
		 String sql = """
		            	select id, name, description, region, city, category, source_category,
		                latitude, longitude, tour_content_id, image_url, homepage_url,
		                1 - (embedding <=> ?::vector) as similarity
				        from places
				        where embedding is not null
				        and 1 - (embedding <=> ?::vector) >= ?
		            	limit ?
		            """;
		String vec = VectorUtil.toVectorString(queryEmbedding);
		//후보 리스트 가져옵니다, RAG(임베딩) 대상만 - Kakao 등 embedding 없는 row는 제외
		return jdbc.query(
				sql,
				PLACE_ROW_MAPPER,
				vec,
				vec,
				k);
				
			
		}
	public List<PlaceResult> searchSimilar(
			float[] queryEmbedding,
            String region,
            String city,
            String category,
            double minSimilarity,
            int k) {
		StringBuilder sql = new StringBuilder("""
		        select id, name, description, region, city, category, source_category,
		               latitude, longitude, tour_content_id, image_url, homepage_url,
		               1 - (embedding <=> ?::vector) as similarity
		        from places
		        where embedding is not null
		          and 1 - (embedding <=> ?::vector) >= ?
		        """);
			
			List<Object> params = new ArrayList<>();
			String vec = VectorUtil.toVectorString(queryEmbedding);
			params.add(vec);
			params.add(vec);
			params.add(minSimilarity);
			
			if (region != null)   { sql.append(" AND region = ? ");   params.add(region); }
			if (city != null)     { sql.append(" AND city = ? ");     params.add(city); }
			if (category != null) { sql.append(" AND category = ? "); params.add(category); }
			
			sql.append(" ORDER BY embedding <=> ?::vector LIMIT ? ");
			params.add(vec);
			params.add(k);
			
			return jdbc.query(sql.toString(), PLACE_ROW_MAPPER, params.toArray());
	}
	
	
	public boolean existsByKakaoPlaceId(String kakaoPlaceId) {
	    Integer cnt = jdbc.queryForObject(
	        "select count(*) from places WHERE kakao_place_id = ?",
	        Integer.class, kakaoPlaceId);
	    return cnt != null && cnt > 0;
	}
 
	public boolean existsByTourContentId(String tourContentId) {
	    Integer cnt = jdbc.queryForObject(
	        "select count(*) from places WHERE tour_content_id = ?",
	        Integer.class, tourContentId);
	    return cnt != null && cnt > 0;
	}
 
	/** tour_content_id로 place의 id를 조회. 없으면 null. (place_programs 저장 시 place_id 매핑용) */
	public Long findIdByTourContentId(String tourContentId) {
	    List<Long> ids = jdbc.query(
	        "select id from places where tour_content_id = ?",
	        (rs, n) -> rs.getLong("id"),
	        tourContentId);
	    return ids.isEmpty() ? null : ids.get(0);
	}
 
	/**
	 * TourAPI 전용 배치 삽입입니다.
	 * ON CONFLICT 대상이 tour_content_id이므로 Kakao 데이터 삽입에는 사용하지 마세요.
	 * (Kakao는 kakao_place_id 기준 별도 메서드(insertKakaoPlaceBatch)를 사용해야 충돌이 정상적으로 잡힙니다.)
	 *
	 * item.embedding()은 null일 수 있습니다 (overview 품질 미달로 임베딩을 만들지 않은 경우).
	 * 이 경우 embedding 컬럼은 NULL로 저장되며, 이후 유사도 검색(searchSimilarTopK/searchSimilar)에서
	 * "embedding IS NOT NULL" 조건으로 자동 제외됩니다. 구조화 메타데이터(좌표/카테고리 등)로는 계속 사용됩니다.
	 */
	public void insertTourApiPlaceBatch(List<PlaceInsert> batchItems) {
	    String sql = """
	        insert into places (name, description, region, city, category, source_category,
	                             latitude, longitude, kakao_place_id, tour_content_id, tour_content_type_id,
	                             image_url, homepage_url, embedding)
	        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::vector)
	        on conflict (tour_content_id) do nothing
	        """;
	    jdbc.batchUpdate(
	            sql,
	            batchItems,
	            batchItems.size(), (ps, item) -> {
	                ps.setString(1, item.name());
	                ps.setString(2, item.description());
	                ps.setString(3, item.region());
	                ps.setString(4, item.city());
	                ps.setString(5, item.category());
	                ps.setString(6, item.sourceCategory());
	                ps.setObject(7, item.latitude());
	                ps.setObject(8, item.longitude());
	                ps.setString(9, item.kakaoPlaceId());
	                ps.setString(10, item.tourContentId());
	                ps.setString(11, item.tourContentTypeId());
	                ps.setString(12, item.imageUrl());
	                ps.setString(13, item.homepageUrl());
	                if (item.embedding() != null) {
	                    ps.setString(14, VectorUtil.toVectorString(item.embedding()));
	                } else {
	                    ps.setString(14, null);
	                    log.warn("TourAPI place inserted without embedding (overview 품질 미달 추정): tourContentId={}, name={}",
	                            item.tourContentId(), item.name());
	                }
	    });
	}
 
	/**
	 * Kakao Local API 전용 배치 삽입입니다.
	 * embedding은 다루지 않습니다 (Kakao 장소는 RAG 대상이 아니므로 NULL로 남습니다).
	 * ON CONFLICT 대상은 kakao_place_id이므로 TourAPI 삽입에는 사용하지 마세요.
	 */
	public void insertKakaoPlaceBatch(List<KakaoPlaceInsert> batchItems) {
	    String sql = """
	        insert into places (name, description, region, city, category, source_category,
	                             latitude, longitude, kakao_place_id)
	        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
	        on conflict (kakao_place_id) do nothing
	        """;
	    jdbc.batchUpdate(
	            sql,
	            batchItems,
	            batchItems.size(), (ps, item) -> {
	                ps.setString(1, item.name());
	                ps.setString(2, item.description());
	                ps.setString(3, item.region());
	                ps.setString(4, item.city());
	                ps.setString(5, item.category());
	                ps.setString(6, item.sourceCategory());
	                ps.setObject(7, item.latitude());
	                ps.setObject(8, item.longitude());
	                ps.setString(9, item.kakaoPlaceId());
	    });
	}
 
	/*****************************Description 다시 임베딩=> 벡터 업데이트*/
 
	/**
	 * 재임베딩 대상 조회입니다.
	 * tour_content_id가 있는 row(TourAPI 출처)만 대상으로 합니다.
	 * Kakao row는 RAG 대상이 아니므로 재임베딩 파이프라인에 포함하지 않습니다.
	 */
	public List<PlaceText> findAllForReembedding(long afterId, int limit){
		String sql =
				"""
				select id, name ,description 
				from places 
				where id > ?
				  and tour_content_id is not null
				order by id
				limit ?  
				""";
		
		return jdbc.query( 
				sql,
				(rs, n)-> new PlaceText(
				rs.getLong("id"),
				rs.getString("name"), 
				rs.getString("description")),
                afterId, 
                limit);
			
	}
	/**
	 * 재임베딩 결과를 반영합니다.
	 * embedding이 null인 항목은 기존 값을 지우지 않도록 업데이트 대상에서 제외하고,
	 * 어떤 id가 스킵되었는지 경고 로그로 남깁니다. (재임베딩 실패로 null이 흘러온 경우
	 * 기존에 정상 저장된 embedding을 NULL로 덮어써서 검색 대상에서 사라지는 사고를 방지)
	 */
	public void updateEmbeddings(List<PlaceEmbedding> items) {
        String sql = """
        		update places 
        		set embedding = ?::vector 
        		WHERE id = ?
        		""";
 
        List<PlaceEmbedding> validItems = new ArrayList<>();
        for (PlaceEmbedding item : items) {
            if (item.embedding() != null) {
                validItems.add(item);
            } else {
                log.warn("재임베딩 결과가 null이라 업데이트를 건너뜁니다: placeId={}", item.id());
            }
        }
 
        if (validItems.isEmpty()) {
            log.warn("updateEmbeddings 호출되었으나 유효한 embedding이 하나도 없어 실행하지 않습니다. 대상 건수={}", items.size());
            return;
        }
 
        jdbc.batchUpdate(sql, validItems, validItems.size(), (ps, item) -> {
            ps.setString(1, VectorUtil.toVectorString(item.embedding()));
            ps.setLong(2, item.id());
        });
    }
	
	/**********************************Description 다시 임베딩=> 벡터 업데이트*/
	
	public record PlaceInsert(
	        String name,
	        String description,
	        String region,
	        String city,
	        String category,
	        String sourceCategory,
	        Double latitude,
	        Double longitude,
	        String kakaoPlaceId,
	        String tourContentId,
	        String tourContentTypeId,
	        String imageUrl,
	        String homepageUrl,
	        float[] embedding)
	{}
 
	public record KakaoPlaceInsert(
	        String name,
	        String description,
	        String region,
	        String city,
	        String category,
	        String sourceCategory,
	        Double latitude,
	        Double longitude,
	        String kakaoPlaceId)
	{}
	
	public record PlaceText(
			long id, 
			String name,
			String description)
	{}
	 public record PlaceEmbedding(
			 long id,
			 float[] embedding) 
	 {}
}