package com.yollo.TravelMate.domain.auth.dto.response;

public class AuthResponseDto {

	public record MobileLogin(
		    boolean isNewUser,      // 신규 유저인가?
		    String tempToken,       // 신규 유저용 5분짜리 임시 토큰 (Register Token)
		    String accessToken,     // 기존 유저용 (신규면 null)
		    String refreshToken     // 기존 유저용 (신규면 null)
		) {}
	
	public record WebLogin(
		    boolean isNewUser,      // 신규 유저인가?
		    String tempToken,       // 신규 유저용 5분짜리 임시 토큰 (Register Token)
		    String accessToken//,   // 기존 유저용 (신규면 null) 
		    //String refreshToken     // 기존 유저용 (신규면 null) 헤더로 보내기 (Local로 받고 컨트롤러에서 추출후 헤더로 보내기) 
		) {}

}
