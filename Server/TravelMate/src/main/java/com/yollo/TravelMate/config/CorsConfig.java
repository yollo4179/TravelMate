package com.yollo.TravelMate.config;

import java.util.List;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class CorsConfig {

	
	@Bean
	 public CorsConfigurationSource corsConfigurationSource() {
		
		CorsConfiguration configuration = new CorsConfiguration();
        
        // 1) 모든 프론트엔드 출처 허용 (개발용)
        configuration.setAllowedOriginPatterns(List.of("*"));
        
        // 2) 모든 HTTP 메서드 허용
        configuration.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"));
        
        // 3) 모든 요청 헤더 허용
        configuration.setAllowedHeaders(List.of("*"));
        
        // 4) 내 인증 정보(쿠키 등) 포함 허용
        configuration.setAllowCredentials(true);
        
        // 🔥 5) [핵심] 프론트엔드(Vue)가 응답 헤더에서 Authorization(JWT 토큰)을 읽을 수 있도록 노출!
        configuration.setExposedHeaders(List.of("Authorization", "authorization")); 

        // 6) 이 설정을 모든 API 경로(/**)에 적용
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", configuration);
        
        return source;
		
			// [주의] allowCredentials(true) 일 때는 allowedOrigins("*") 사용 불가
            // 고정 IP/DNS가 없는 환경에서 쿠키 통신을 허용하기 위해 패턴 패턴 방식(*) 사용
			// 프론트엔드의 HttpOnly 쿠키(Refresh Token) 송수신을 허용
            // 자바스크립트의 withCredentials = true 설정과 쌍을 이룸
			
			/* * [참고] Spring Security 필터 단에서 Preflight(OPTIONS) 요청을 1차 허용했더라도,
             * 실제 본 요청(GET, POST 등)이 DispatcherServlet(MVC) 단까지 들어왔을 때 
             * 브라우저가 요구하는 CORS 응답 헤더(Access-Control-Allow-*)를 정상적으로 생성하기 위해 
             * WebMvcConfigurer 설정을 추가로 정의함.
             */
	}
}