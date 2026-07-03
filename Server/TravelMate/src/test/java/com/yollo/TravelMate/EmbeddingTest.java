package com.yollo.TravelMate;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.util.Pair;

import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.data.entity.Place;
import com.yollo.TravelMate.domain.place.repository.PlaceJpaRepository;
import com.yollo.TravelMate.domain.place.repository.PlaceVectorRepository;



@SpringBootTest
public class EmbeddingTest {

	 @Autowired
	 PlaceVectorRepository repo;
	 @Autowired
	 PlaceJpaRepository jpaRepo;
	 @Autowired
	 EmbeddingClient embeddingClient;
	 
	 private static final String GREEN = "\u001B[32m";
	 private static final String YELLOW = "\u001B[33m";
	 private static final String RED = "\u001B[31m";
	 private static final String RESET = "\u001B[0m";

	 
	
	private static final Logger log = LoggerFactory.getLogger(EmbeddingTest.class);
//	@Test
//	public void ClearAll() {
//		 jpaRepo.deleteAll();
//		 
//	 }

	public record EmbeddingTestParams(
			String description,
			String region,
			String city
			) {}
	
	@Test
	public void run() {

	        
	        List<EmbeddingTestParams> queries = 
	        		List.of(
	        				new EmbeddingTestParams("아이랑 가기 좋은 풀빌라","경기" ,"가평"),
	        				new EmbeddingTestParams("밥 먹기 좋은 곳","서울","서울"),
	        				new EmbeddingTestParams("조용히 쉬고 싶어","서울","서울"),
	        				new EmbeddingTestParams("역사 공부하고 싶어","서울","서울"),
	        				new EmbeddingTestParams("스키장 리프트권 할인", "","")  // threshold 동작 확인용
	        				); 
	        queries.forEach(
	        		it->{
	        			String nowRegion = it.region.isEmpty() ? null : it.region;
	        			String nowCity = it.city.isEmpty() ? null : it.city;
	        			String nowQuery = it.description() ;
	        			
	        			float[] nowEmbedding = embeddingClient.embed( nowQuery);
	        			log.info("{}=== 검색: {}==={}",RED,nowQuery,RESET);
	        			repo
	        			.searchSimilar(nowEmbedding, nowRegion, nowCity, null, 0.3, 10)
	        			.forEach( (r) -> {
	        		        	
	        			        String similarity = String.format("%.4f", r.similarity());
	        			        log.info("{}{}->유사도: {}{}{}:city:{}",RED,r.name(),GREEN ,similarity, RESET,r.city());
	        			 });
	        			 
	        		});
		
	       
	    }

	
}
