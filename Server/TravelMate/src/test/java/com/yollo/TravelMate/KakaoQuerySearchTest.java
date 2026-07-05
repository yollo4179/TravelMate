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
  	               "공감호스텔 동성로(공감동성로게스트하우스)",
  	             "군위 상매댁(군위남천고택)",
  	           "글렌즈 게스트하우스(글렌즈게스트하우스)",
  	         "대구 메리어트 호텔",
  	       "도동유교문화관",
  	     "브라운도트 호텔 대구수성점",
  	   "비바스호텔",
  	 "빌리언웨스턴호텔 대구성서점",
  	"사라네집",
  	"상상하우스",
  	"서문한옥게스트하우스",
  	"스테이 원향",
  	"시안호텔",
  	"애가 한옥 게스트하우스",
  	"여주현_감성독채한옥숙소",
  	"유니드호텔",
  	"유원게스트하우스",
  	"컨벤션비지니스호텔",
  	 "팔공 에밀리아호텔",
  	"한옥,만월 프리미엄스테이"
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

//	    @Test
//	    @DisplayName("단일 키워드 상세 확인")
//	    void searchByKeyword_단일() {
//	        List<KakaoPlaceResponseDto> results = kakaoService.searchByKeyword("서울 체험·액티비티");
//	        results.forEach(p -> System.out.println(
//	                p.placeName() + " / " + p.categoryName()
//	                + " / kakaoId=" + p.kakaoPlaceId()));
//	    }
}
