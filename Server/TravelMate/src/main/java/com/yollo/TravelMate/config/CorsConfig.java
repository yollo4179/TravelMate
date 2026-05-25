package com.yollo.TravelMate.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class CorsConfig {

	
	@Bean
	public WebMvcConfigurer  corsConfigurer() {
		
		return new WebMvcConfigurer() {
			@Override
			public void addCorsMappings(CorsRegistry registry) {
				 registry.addMapping("/**")
				 .allowedOriginPatterns("*") //나 dns 없으니까 ,cors 피하려면 얘랑 + allowCredentials(true) 필요 
                 .allowedMethods("*")
                 .allowedHeaders("*")
                 .allowCredentials(true);
				 /*필터에서 preflight 허용하였지만 추가 로 정의해야할 것들 mvc 설정에서 처리*/
				 /* 실제 CORS 허용 정책을 정의 */
				 /* 브라우저의 preflight 요청에 대해
				    (허용되는)Access-Control-Allow-* 응답 헤더를 생성 */
			};
		
			// [주의] allowCredentials(true) 일 때는 allowedOrigins("*") 사용 불가
            // 고정 IP/DNS가 없는 환경에서 쿠키 통신을 허용하기 위해 패턴 패턴 방식(*) 사용
			// 프론트엔드의 HttpOnly 쿠키(Refresh Token) 송수신을 허용
            // 자바스크립트의 withCredentials = true 설정과 쌍을 이룸
			
			/* * [참고] Spring Security 필터 단에서 Preflight(OPTIONS) 요청을 1차 허용했더라도,
             * 실제 본 요청(GET, POST 등)이 DispatcherServlet(MVC) 단까지 들어왔을 때 
             * 브라우저가 요구하는 CORS 응답 헤더(Access-Control-Allow-*)를 정상적으로 생성하기 위해 
             * WebMvcConfigurer 설정을 추가로 정의함.
             */
		};
	}
}