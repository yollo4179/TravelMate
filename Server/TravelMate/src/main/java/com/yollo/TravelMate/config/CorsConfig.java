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
                 .allowedOrigins("*")
                 .allowedMethods("*")
                 .allowedHeaders("*");
				 /*필터에서 preflight 허용하였지만 추가 로 정의해야할 것들 mvc 설정에서 처리*/
				 /* 실제 CORS 허용 정책을 정의 */
				 /* 브라우저의 preflight 요청에 대해
				    (허용되는)Access-Control-Allow-* 응답 헤더를 생성 */
			};
		
		};
	}
}