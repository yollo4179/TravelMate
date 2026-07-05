package com.yollo.TravelMate.domain.place.service;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.data.response.KakaoPlaceResponseDto;
import com.yollo.TravelMate.domain.place.enums.PlaceCategory;
import com.yollo.TravelMate.domain.place.enums.RegionData;
import com.yollo.TravelMate.domain.place.enums.RegionData.City;
import com.yollo.TravelMate.domain.place.repository.PlaceVectorRepository;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class PlaceCollectorService {

	/*컬렉터는 카카오 API로부터 장소를 검색해 놓고 DB에 배치로 저장합니다.*/
	
	private static final Logger log = LoggerFactory.getLogger(PlaceCollectorService.class);
	
	private final KakaoLocalService kakaoLocalService;
	private final EmbeddingClient embeddingClient;
	private final PlaceVectorRepository placeRepository;
	private static final int BATCH_SIZE = 64;
	private int consecutiveFlushFailures = 0;
	private static final int MAX_FLUSH_FAILURES = 3;
	public void healthCheck() {
		try {
	        embeddingClient.embed("health check");
	    } catch (Exception e) {
	        throw new IllegalStateException(
	            "임베딩 서버 연결 불가. 수집을 중단합니다. FastAPI(8000) 먼저 실행하세요.", e);
	    }
		
	}
	public CollectResult collectAll(List<City> cityFilter) {
		 
		healthCheck();
		 int 
		 searched = 0,
		 inserted = 0,
		 skippedDup = 0,
		 skippedRegion = 0;
		 
		 //원하는 필터가 없으면 전체를 조회합니다.
		 List<City> cities = 
				 (cityFilter!= null) ? cityFilter
					 : List.of(City.values());
		 
		 List<Candidate> buffer = new ArrayList<>(); //임베딩 전 후보들
		 Set<String> seenIds = new HashSet<>();// 이번 수집 세션 내 중복 방지
		 
		 
		 for (City city : cities) { //지역 필터
			 for (PlaceCategory category : PlaceCategory.values()) { //카테고리 필터
				 for(String keyword :category.getKeywords()) {
					 String query = city.getSearchName() +" " + keyword;
					 searched++;
					 List<KakaoPlaceResponseDto> results;
					 try {
	                        results = kakaoLocalService.searchByKeyword(query);
	                 } catch (Exception e) {
	                        log.warn("검색 실패: {} - {}", query, e.getMessage());
	                        continue;
	                 }
					 
					 for (KakaoPlaceResponseDto p : results) {
	                        // 1) 지역 검증: 주소에 검색 도시명이 없으면 다른 지역 오검색으로 간주
	                        if (!isRegionMatched(p, city)) { skippedRegion++; continue; }

	                        // 2) 중복: 같은 kakaoPlaceId 이미 있으면 스킵
	                        if (!seenIds.add(p.kakaoPlaceId())) { skippedDup++; continue; }
	                        
	                        //3) 이미 : db에 있는지 확인
	                        if (placeRepository.existsByKakaoPlaceId(p.kakaoPlaceId())) {
	                            skippedDup++; continue;
	                        }
	                        // 3) 설명 텍스트 구성 (허브 완화)
	                        String description = buildDescription(p, city, category);
	                        buffer.add(new Candidate(p, city, category, description));
	                        
	                        //배치 꽏차면 DB에 일괄처리합니다.
	                        if (buffer.size() >= BATCH_SIZE) {
	                            inserted += flush(buffer);
	                        }
	                       
					 }
				 }
			 }
			 log.info("[{}] 진행 - 누적 적재 {}건", city.getSearchName(), inserted); 
		 }
		 /*딱 맞아 떨어지지 않는다.*/
		 if (!buffer.isEmpty()) {
	            inserted += flush(buffer);
	     }
		 
		 return new CollectResult(searched, inserted, skippedDup, skippedRegion);
	 }
	  private int flush(List<Candidate> buffer) {
	        // 임베딩 대상 텍스트: "이름. 설명"
	        List<String> texts = buffer.stream()
	                .map(c -> c.dto().placeName() + ". " + c.description())
	                .toList();

	        List<float[]> embeddings;
	        try {
	            embeddings = embeddingClient.embedBatch(texts);   // 한 번의 HTTP로 N건
	        } catch (Exception e) {
	        	if (++consecutiveFlushFailures >= MAX_FLUSH_FAILURES) {
	                throw new IllegalStateException("임베딩 서버 연속 " + MAX_FLUSH_FAILURES + "회 실패 - 수집 중단", e);
	            }
	            log.error("배치 임베딩 실패 ({}건) - 이 배치 건너뜀: {}", buffer.size(), e.getMessage());
	            buffer.clear();
	            return 0;
	        }
	        consecutiveFlushFailures = 0;
	        List<PlaceVectorRepository.KakaoPlaceInsert> inserts = new ArrayList<>(buffer.size());
	        for (int i = 0; i < buffer.size(); i++) {
	            Candidate nowC = buffer.get(i);
	            float[] nowEmbedding = embeddings.get(i);
	            
	            inserts.add(new PlaceVectorRepository.KakaoPlaceInsert(
	            		nowC.dto().placeName(),
	            		nowC.description(),
	            		nowC.city().getRegion(),
	            		nowC.city().getSearchName(),
	            		nowC.category().getLabel(),
	            		nowC.dto().categoryName(),
	            		nowC.dto().latitude(),
	            		nowC.dto().longitude(),
	            		nowC.dto().kakaoPlaceId()));
	        }
	        //DB 
	        placeRepository.insertKakaoPlaceBatch(inserts);

	        //클리어
	        int n = buffer.size();
	        buffer.clear();
	        log.info("배치 적재 {}건", n);
	        return n;
	    }
	 
	/*0*
     * 전체 도시 × 카테고리 키워드 순회하며 수집·적재.
     * @param cityFilter null이면 전체, 아니면 해당 도시들만 (쿼터 분할 수집용)
     */
	
	
	 private boolean isRegionMatched(KakaoPlaceResponseDto p, City city) {
	        if (p.roadAddress() == null) return true; // 주소 없으면 일단 통과 
	        // "서울"처럼 광역이거나 "가평"처럼 시군이거나, 주소에 도시명 또는 광역명이 있으면 OK
	        return p.roadAddress().contains(city.getSearchName())
	                || p.roadAddress().contains(city.getRegion());
	   }
	 private String buildDescription(KakaoPlaceResponseDto p, City city, PlaceCategory category) {
	        StringBuilder sb = new StringBuilder();
	        if (p.categoryName() != null) {
	            // "여행 > 관광,명소 > 전망대" → "관광 명소 전망대"
	            String cat = 
	            		p
	            		.categoryName()
	            		.replace(",", " ")
	            		.replace(" > ", " ");
	            sb.append(cat).append(". ");
	        }
	        sb
	        .append(" ")
	        .append(city.getRegion());
	        
	        if (!city.getRegion().equals(city.getSearchName())) {
	            sb.append(" ").append(city.getSearchName());
	        }
	        
	        return sb.toString().trim();
	    }
	
	 
	 private record Candidate(
			 KakaoPlaceResponseDto dto,
			 RegionData.City city,
             PlaceCategory category,
             String description)
	 {}
	 public record CollectResult(
			 int searched, 
			 int inserted,
			 int skippedDup,
			 int skippedRegion) 
	 {}

}
