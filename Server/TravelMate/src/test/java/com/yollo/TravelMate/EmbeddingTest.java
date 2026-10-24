package com.yollo.TravelMate;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.util.Pair;

import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.repository.PlaceSemanticSearchRepository;



@SpringBootTest
public class EmbeddingTest {

	 @Autowired
	 PlaceSemanticSearchRepository repo;
	 @Autowired
	 EmbeddingClient embeddingClient;
	 
	 private static final String GREEN = "\u001B[32m";
	 private static final String YELLOW = "\u001B[33m";
	 private static final String RED = "\u001B[31m";
	 private static final String RESET = "\u001B[0m";

	 
	
	private static final Logger log = LoggerFactory.getLogger(EmbeddingTest.class);
//	@Test
//	public void ClearAll() {
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
		                new EmbeddingTestParams("낡지만 귀중한 전통의 물건들이 교류되는 소중한 공\r\n"
                        + "간이다. 인사동에는 큰 대로를 중심으로 사이사이 골목들이 미로처럼 얽혀 있다. 이 미로 속에는 화랑, 전통공예점, 고미술점,\r\n"
                        + "전통찻집, 전통음식점, 카페 등이 밀집되어 있다. 특히 인사동의 가게들은 저마다의 독특한 멋으로 젊은이들은 물론 중년층에게\r\n"
                        + "까지 매우 인기가 많다. 그중에서도 화랑은 인사동의 맥을 이어온 중심이다. 이곳에는 100여 개의 화랑이 밀집되어 있는데 한국\r\n"
                        + "화에서 판화, 조각전까지 다양한 전시회를 감상할 수 있다. 대표적인 화랑으로는 민중미술의 중심역할을 했던 학고재, 재능 있는\r\n"
                        + " 작가들의 터전이 되었던 가나화랑, 가나아트센터 등이 있다. 만약 인사동의 유명한 화랑만을 골라서 편하게 구경하고 싶다면 미\r\n"
                        + "술관 순화버스를 이용해 보자. 저렴한 가격으로 유명 화랑 10여 곳을 둘러볼 수 있다. 화랑과 함께 인사동 거리를 메우고 있는\r\n"
                        + "것은 바로 전통 찻집과 음식점이다." ,"",""),           // 관문3과 비교 가능 (before/after)
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
		          
		            repo.searchSimilar(nowEmbedding,null,  "종로", null, 0, 10)
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
