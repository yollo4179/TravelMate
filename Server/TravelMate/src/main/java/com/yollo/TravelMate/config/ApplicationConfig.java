package com.yollo.TravelMate.config;
import java.sql.Driver;
import java.util.List;

import javax.sql.DataSource;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.SimpleDriverDataSource;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

@Configuration
@EnableWebSecurity
public class ApplicationConfig {
	 @SuppressWarnings("unchecked")
		
	    @Bean
	    public DataSource dataSource() {
	    	//SimpleDriverDataSource 이란
	        //스프링에서 connection을 관리해주는 클래스, connection을 관리한다.  
	    	SimpleDriverDataSource ds = new SimpleDriverDataSource();
	        try {
				ds.setDriverClass((Class<Driver>) Class.forName("org.postgresql.Driver"));
			} catch (ClassNotFoundException e) {
				e.printStackTrace();
			}
	        ds.setUrl("jdbc:postgresql://127.0.0.1:5432/TravelMate?serverTimezone=Asia/Seoul&useUniCode=yes&characterEncoding=UTF-8");
	        ds.setUsername("ssafy");
	        ds.setPassword("ssafy");
	        return ds;
	    }
	 
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
	    }
}




