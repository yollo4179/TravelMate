package com.yollo.TravelMate.jwt.config;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

import com.yollo.TravelMate.jwt.JwtAuthenticationFilter;
import com.yollo.TravelMate.jwt.JwtTokenProvider;

import lombok.RequiredArgsConstructor;

@Configuration
@EnableWebSecurity
@RequiredArgsConstructor // JwtTokenProvider 주입을 위해 사용
public class SecurityConfig {

	@Autowired
    private final JwtTokenProvider tokenProvider; // 빈으로 등록된 프로바이더 주입
	@Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(); // 권장되는 기본 암호화 알고리즘
    }
    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .csrf(csrf -> csrf.disable())// JWT를 사용하므로 CSRF 보호 비활성화
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))//세션 사용 x 
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/api/login", "/api/refresh").permitAll() // 로그인, 재발급은 통과
                .anyRequest().authenticated()  //나머지 모든 API는 반드시 유효한 토큰이 있어야만 접근
            ).addFilterBefore(new JwtAuthenticationFilter(tokenProvider), UsernamePasswordAuthenticationFilter.class);
        	//오버라이드 함수가 다 검증해줄거임
        return http.build();
    }
    
    ///api/user/send
    /// /api/refresh
    /// 
}