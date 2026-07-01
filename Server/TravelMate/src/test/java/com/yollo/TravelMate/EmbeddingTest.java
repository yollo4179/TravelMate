package com.yollo.TravelMate;

import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

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
	@Test
	public void ClearAll() {
		 jpaRepo.deleteAll();
		 
	 }
	
	@Test
	public void run() {
		 	insert("남산서울타워", "서울 도심 전망 명소, 케이블카와 야경");
	        insert("롯데월드타워", "잠실 초고층 전망대 서울스카이");
	        insert("인왕 산", "산꼭대기 위에서 보는 절경,화려한 야경은 덤으로.");
	        insert("경복궁", "조선시대 궁궐, 한복 체험과 수문장 교대식");
	        insert("광장시장", "전통시장, 빈대떡과 마약김밥 먹거리");
	        
	        
	        float[] query = embeddingClient.embed( "데이트 하기 좋은 장소" );
	        log.info("{}=== 검색: 데이트 하기 좋은 장소==={}",RED,RESET);
	        repo.searchSimilarTopK(query, 5).forEach( (r) -> {
	        	
	        String similarity = String.format("%.4f", r.similarity());
	        log.info("{}{}->유사도: {}{}{}",RED,r.name(),GREEN ,similarity, RESET);
	        });
	        //ClearAll();
	    }

	    
	    private void insert(String name, String desc) {
	        float[] emb = embeddingClient.embed(name + " " + desc);
	        
	        log.debug("emb"+emb.length);
	        repo.insertPlace( name, desc, "서울", null, null, null, emb);
	    }
}
