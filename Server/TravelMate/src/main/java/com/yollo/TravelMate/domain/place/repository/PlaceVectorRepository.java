package com.yollo.TravelMate.domain.place.repository;

import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.util.VectorUtil;

@Repository
public class PlaceVectorRepository {
	
	private final JdbcTemplate jdbc;
	
	public PlaceVectorRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }
	
	public void insertPlace(
			String name,
			String description,
			String region,
            String category,
            Double lat,
            Double lng, 
            float[] embedding) {
		
		
		String sql = """
				insert into places
				(name,description,region,category,latitude,longitude,embedding)
				values(?,?,?,?,?,?,?::vector)""";
		 jdbc.update(sql, name, description, region, category, lat, lng,
                 VectorUtil.toVectorString(embedding));

	}
	
	public List<PlaceResult> searchSimilarTopK(float queryEmbedding[], int k) {
		
		
		String sql =""" 
				select id, name,description,region,category,latitude,longitude,
					   1 - (embedding <=> ?::vector) as similarity
				from places
				order by embedding <=> ?::vector
				limit ?
				""";
		String vec = VectorUtil.toVectorString(queryEmbedding);
		//후보 리스트 가져옵니다,
		return jdbc.query(
				sql,
				(rs,rowNum)->new PlaceResult(
						rs.getLong("id"),
		                rs.getString("name"),
		                rs.getString("description"),
		                rs.getString("region"),
		                rs.getString("category"),
		                rs.getDouble("latitude"),
		                rs.getDouble("longitude"),
		                rs.getDouble("similarity")
						),vec,vec,k);
				
			
		}
		
		
	}
	
