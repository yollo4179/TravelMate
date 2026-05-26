package com.yollo.TravelMate.cookies;

import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;

@Component
public class CookieUtil {

	
	public ResponseCookie createRefreshTokenCookie(String refreshToken, long maxAgeSeconds) {
        return ResponseCookie.from("refreshToken", refreshToken)
                .httpOnly(true)    // JavaScript 크큐 못읽음 (XSS 방어)
                .secure(false)     //일단 http + https 모두 허용 패킷강탈막으려면 true
                .path("/") 
                .maxAge(maxAgeSeconds)
                .build();
    }
	
	public ResponseCookie createEmptyCookie() {
        return ResponseCookie.from("refreshToken", "")
                .httpOnly(true)
                .secure(false) 
                .path("/")
                .maxAge(0) // 수명을 0으로 주면 브라우저가 즉시 삭제함
                .build();
    }
}
