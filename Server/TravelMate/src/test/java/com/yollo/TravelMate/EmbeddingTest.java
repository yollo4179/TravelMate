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
	public void tourApiEmbeddingTest() {
		
		List<EmbeddingTestParams> queries =
		        List.of(
		                new EmbeddingTestParams("역사 공부하고 싶어" ,"",""),           // 관문3과 비교 가능 (before/after)
		                new EmbeddingTestParams("경복궁 근처 가볼만한 곳","",""),        // TourAPI 관광지 맞춤 신규 쿼리
		                new EmbeddingTestParams("공원에서 산책하고 싶어", "", ""),         // 훈련원공원류 검증
		                new EmbeddingTestParams("전통문화 체험하고 싶어", "", ""),         // 문화·역사 계열
		                new EmbeddingTestParams("스키장 리프트권 할인", "", "")                    // threshold 검증 (데이터 무관)
		        );

		queries.forEach(
		        it -> {
		            String nowRegion = it.region.isEmpty() ? null : it.region;
		            String nowCity = it.city.isEmpty() ? null : it.city;
		            String nowQuery = it.description();

		            float[] nowEmbedding = embeddingClient.embed(nowQuery);
		            
		            log.info("{}=== 검색: {}==={}", RED, nowQuery, RESET);
		          
		            repo.searchSimilar(nowEmbedding, nowRegion, nowCity, null, 0, 10)
		                .forEach((r) -> {
		                    String similarity = String.format("%.4f", r.similarity());
		                    log.info("{}{}->유사도: {}{}{}:city:{}:src:{}",
		                            RED, r.name(), GREEN, similarity, RESET, r.city(),
		                            r.tourContentId() != null ? "TourAPI" : "Kakao");
		                });
		        });
	}
	
//	@Test
//	public void KakaoApiEmbeddingTest() {
//
//	        
//	        List<EmbeddingTestParams> queries = 
//	        		List.of(
//	        				new EmbeddingTestParams("아이랑 가기 좋은 풀빌라","경기" ,"가평"),
//	        				new EmbeddingTestParams("밥 먹기 좋은 곳","서울","서울"),
//	        				new EmbeddingTestParams("조용히 쉬고 싶어","서울","서울"),
//	        				new EmbeddingTestParams("역사 공부하고 싶어","서울","서울"),
//	        				new EmbeddingTestParams("스키장 리프트권 할인", "","")  // threshold 동작 확인용
//	        				); 
//	        queries.forEach(
//	        		it->{
//	        			String nowRegion = it.region.isEmpty() ? null : it.region;
//	        			String nowCity = it.city.isEmpty() ? null : it.city;
//	        			String nowQuery = it.description() ;
//	        			
//	        			float[] nowEmbedding = embeddingClient.embed( nowQuery);
//	        			log.info("{}=== 검색: {}==={}",RED,nowQuery,RESET);
//	        			repo
//	        			.searchSimilar(nowEmbedding, nowRegion, nowCity, null, 0.3, 10)
//	        			.forEach( (r) -> {
//	        		        	
//	        			        String similarity = String.format("%.4f", r.similarity());
//	        			        log.info("{}{}->유사도: {}{}{}:city:{}",RED,r.name(),GREEN ,similarity, RESET,r.city());
//	        			 });
//	        			 
//	        		});
//		
//	       
//	    }

	
}
