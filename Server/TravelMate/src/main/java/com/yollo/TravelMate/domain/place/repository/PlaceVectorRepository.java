package com.yollo.TravelMate.domain.place.repository;

import java.util.ArrayList;
import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.util.VectorUtil;

@Repository
public class PlaceVectorRepository {
	
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
		        rs.getDouble("similarity"));

	
	public List<PlaceResult> searchSimilarTopK(float queryEmbedding[], int k) {
		
		
		String sql =""" 
				select id, name,description,region,city,category, source_category,latitude,longitude,
					   1 - (embedding <=> ?::vector) as similarity
				from places
				order by embedding <=> ?::vector
				limit ?
				""";
		String vec = VectorUtil.toVectorString(queryEmbedding);
		//후보 리스트 가져옵니다,
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
			SELECT id, name, description, region, city, category, source_category, latitude, longitude,
			1 - (embedding <=> ?::vector) AS similarity
			FROM places
			WHERE 1 - (embedding <=> ?::vector) >= ?
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
	/*삽입 로직 배치 방식으로 수정합니다.*/
	public void insertPlaceBatch(List<PlaceInsert>batchItems) {
		String sql = """
			    insert into places (name, description, region, city, category, source_category ,latitude, longitude, kakao_place_id, embedding)
			    values (?, ?, ?, ?, ?, ?, ? ,?, ?, ?::vector)
			    on conflict (kakao_place_id) do nothing
			    """;
	    jdbc.batchUpdate( 
	    		sql, 
	    		batchItems,
	    		batchItems.size(),(ps,item)->{
	    			ps.setString(1, item.name());
		            ps.setString(2, item.description());
		            ps.setString(3, item.region());
		            ps.setString(4, item.city());
		            ps.setString(5, item.category());
		            ps.setString(6, item.sourceCategory());
		            ps.setObject(7, item.latitude());
		            ps.setObject(8, item.longitude());
		            ps.setString(9, item.kakaoPlaceId());
		            ps.setString(10, VectorUtil.toVectorString(item.embedding()));
	    });
	}
	/*****************************Description 다시 임베딩=> 벡터 업데이트*/
	public List<PlaceText> findAllForReembedding(long afterId, int limit){
		String sql =
				"""
				select id, name ,description 
				from places 
				where id > ?
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
	public void updateEmbeddings(List<PlaceEmbedding> items) {
        String sql = """
        		update places 
        		set embedding = ?::vector 
        		WHERE id = ?
        		""";
        jdbc.batchUpdate(sql, items, items.size(), (ps, item) -> {
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
	        float[] embedding) 
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
	
