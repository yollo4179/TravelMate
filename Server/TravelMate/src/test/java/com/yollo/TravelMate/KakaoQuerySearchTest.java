package com.yollo.TravelMate;

import java.util.List;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import com.yollo.TravelMate.domain.place.data.response.KakaoPlaceResponseDto;
import com.yollo.TravelMate.domain.place.service.KakaoLocalService;


@SpringBootTest
public class KakaoQuerySearchTest {
	
	@Autowired
	KakaoLocalService kakaoService;
	 	@Test
	    @DisplayName("여러 키워드로 Kakao 검색 결과와 카테고리 확인")
	    void searchByKeyword_다양한키워드() {
	        List<String> keywords = List.of(
	                "서울 관광명소",
	                "서울 전망대",
	                "서울 고궁",
	                "동성로",
	                "서울 맛집",
	                "서울 카페",
	                "서울 공원",
	                "서울 숙소",
	                "서울 버스 정류장",
	                "공항",
	                "백화점",
	                "박물관"
	               
	        );

	        for (String keyword : keywords) {
	            System.out.println("\n========== 키워드: [" + keyword + "] ==========");
	            List<KakaoPlaceResponseDto> results;
				try {
					results = kakaoService.searchByKeyword(keyword);
					System.out.println("결과 수: " + results.size());

		            results.forEach(p -> System.out.printf(
		                    "  %-20s | cat=%-30s | (%.5f, %.5f) | %s%n",
		                    p.placeName(),
		                    p.categoryName(),
		                    p.latitude(),
		                    p.longitude(),
		                    p.roadAddress()
		            ));	
				} catch (Exception e) {
					// TODO Auto-generated catch block
					e.printStackTrace();
				}finally {
				
				}
	            
	        }
	    }

	    @Test
	    @DisplayName("단일 키워드 상세 확인")
	    void searchByKeyword_단일() {
	        List<KakaoPlaceResponseDto> results = kakaoService.searchByKeyword("남산서울타워");
	        results.forEach(p -> System.out.println(
	                p.placeName() + " / " + p.categoryName()
	                + " / kakaoId=" + p.kakaoPlaceId()));
	    }
}
