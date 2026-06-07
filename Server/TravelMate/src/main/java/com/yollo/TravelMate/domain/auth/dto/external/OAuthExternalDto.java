package com.yollo.TravelMate.domain.auth.dto.external;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

public class OAuthExternalDto {

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record Kakao(
		    String iss,   // 발행자 정보
		    String aud,   // 서비스 앱 키
		    String sub,   // 카카오 고유 ID
		    Long iat,     // 발급 시간
		    Long exp,     // 만료 시간
		    String email  // 이메일
		) {}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record Naver(
		    String resultcode,
		    String message,
		    Response response // 👈 진짜 데이터가 담긴 알맹이 객체
		) {
		    
		    public record Response(
		        String id,          // 네이버 고유 식별자 (DB에 저장할 값)
		        String email,
		        String name,
		        String nickname,
		        String profile_image
		    ) {}
		}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record Google(
		    String iss,   // 발행자 (https://accounts.google.com)
		    String sub,   // 구글 고유 ID (DB에 저장할 값)
		    String email, // 이메일
		    String name,  // 이름
		    String picture // 프로필 사진 URL
		) {}
}
