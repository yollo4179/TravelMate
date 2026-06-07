package com.yollo.TravelMate.domain.auth.dto.request;

import jakarta.validation.constraints.NotBlank;

public class AuthRequestDto {

	// 로그인 요청
	public record LocalLogin(
		    @NotBlank(message = "아이디(또는 이메일)는 필수입니다.") 
		    String userId,
		    @NotBlank(message = "비밀번호는 필수입니다.") 
		    String password
		) {}
	
	// android는 로그인처리만 합니다. 2단계 로그인 구조 
	public record SocialLogin(
		    @NotBlank(message = "Provider는 무조건 설정해야 합니다. (KAKAO, GOOGLE)") 
		    String provider,
		    
		    @NotBlank(message = "소셜 인증 토큰(idToken)은 필수입니다.") 
		    String idToken
		) {}

	public record OAuthSignup(
		    @NotBlank(message = "닉네임을 입력해주세요.") 
		    String nickname
		) {}
}
