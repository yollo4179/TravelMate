package com.yollo.TravelMate.domain.auth.dto.internal;

public record UserInfo(
	    String provider,    // KAKAO, GOOGLE 
	    String providerId,  // 플랫폼별 고유 ID (subject)
	    String email,       // 공통으로 받을 수 있는 정보
	    String nickname     // 공통으로 받을 수 있는 정보
	) {}
