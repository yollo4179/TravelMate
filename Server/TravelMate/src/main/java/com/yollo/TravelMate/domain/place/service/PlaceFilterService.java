package com.yollo.TravelMate.domain.place.service;

import java.util.List;

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
public class PlaceFilterService {

	
	
	private static final Logger log = LoggerFactory.getLogger(PlaceFilterService.class);
	
	private final KakaoLocalService kakaoLocalService;
	private final EmbeddingClient embeddingClient;
	private final PlaceVectorRepository placeRepository;
	public record CollectResult(
			 int searched,
			 int inserted,
			 int skippedDup,
			 int skippedRegion)
	 {}
	 public CollectResult collectAll(List<City> cityFilter) {
		 
		 int 
		 searched = 0,
		 inserted = 0,
		 skippedDup = 0,
		 skippedRegion = 0
		 
		 //원하는 필터가 없으면 전체를 조회합니다.
		 List<City> cities = 
				 (cityFilter!= null) ? cityFilter
					 : List.of(City.values());
		 
		 
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
	                        if (placeRepository.existsByKakaoPlaceId(p.kakaoPlaceId())) {
	                            skippedDup++; continue;
	                        }

	                        // 3) 설명 텍스트 구성 (허브 완화)
	                        String description = buildDescription(p, city, category);

	                        // 4) 임베딩 (이름 + 설명)
	                        float[] emb;
	                        try {
	                            emb = embeddingClient.embed(p.placeName() + ". " + description);
	                        } catch (Exception e) {
	                            log.warn("임베딩 실패: {}", p.placeName());
	                            continue;
	                        }

	                        // 5) 적재
	                        placeRepository.insertPlace(
	                                p.placeName(), description,
	                                city.getRegion(), category.getLabel(),
	                                p.latitude(), p.longitude(),
	                                p.kakaoPlaceId(), emb);
	                        inserted++;
	                    }			 
				 }
				 
			 }
			 log.info("[{}] 진행 - 누적 적재 {}건", city.getSearchName(), inserted); 
		 }
		
		 return new CollectResult(searched, inserted, skippedDup, skippedRegion);
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
	        sb
	        .append(city.getRegion())
	        .append("에 위치한 ")
	        .append(category.getLabel())
	        .append(" 명소. ");
	        if (p.categoryName() != null) {
	            // "여행 > 관광,명소 > 전망대" → "관광 명소 전망대"
	            String cat = p.categoryName().replace(",", " ").replace(" > ", " ");
	            sb.append(cat).append(". ");
	        }
	        return sb.toString().trim();
	    }
	
}
