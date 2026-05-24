package com.yollo.TravelMate.jwt.config;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.servlet.HandlerExceptionResolver;

import com.yollo.TravelMate.domain.user.service.UserService;
import com.yollo.TravelMate.jwt.JwtTokenProvider;
import com.yollo.TravelMate.jwt.Filters.JwtAuthenticationFilter;
import com.yollo.TravelMate.jwt.Filters.JwtExceptionFilter;

import lombok.RequiredArgsConstructor;

@Configuration
@EnableWebSecurity

public class SecurityConfig {


    private final JwtTokenProvider tokenProvider; // 빈으로 등록된 프로바이더 주입
	private final UserService userService;
	private final HandlerExceptionResolver handlerExceptionResolver;
	public SecurityConfig(
            JwtTokenProvider tokenProvider, 
            UserService userService,
            @Qualifier("handlerExceptionResolver") HandlerExceptionResolver handlerExceptionResolver // 여기에 명확히 주입
    ) {
        this.tokenProvider = tokenProvider;
        this.userService = userService;
        this.handlerExceptionResolver = handlerExceptionResolver;
    }
    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
        	.cors(cors -> {})
        	/* Spring Security가 MVC의 CORS 설정을 사용하도록 활성화 */
        	.csrf(csrf -> csrf.disable())
        	/* JWT Authorization 헤더 기반 인증 사용
        	   (세션 쿠키 기반 인증이 아니므로)
        	   기본 CSRF 보호 비활성화 */
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            /* 서버 세션 사용 안 함
            매 요청마다 JWT 토큰 검증 */ 
            .authorizeHttpRequests(auth -> auth
            	.requestMatchers(HttpMethod.OPTIONS, "/**").permitAll() 
            	/* 브라우저의 CORS preflight(OPTIONS) 요청은
            	   인증 없이 허용 +나중에 mvc에서 헝용정보 생성*/
                .requestMatchers(
                		"/api/auth/login", 
                		"/api/auth/refresh", 
                		"/api/users/signup", 
                		"/api/users/checkUserId", 
                		"/api/users/checkNickname",  
                		"/"
                		).permitAll() 
                /* 로그인, 재발급은 통과*/
                .anyRequest().authenticated()  //나머지 모든 API는 반드시 유효한 토큰이 있어야만 접근
            )
            .addFilterBefore(new JwtAuthenticationFilter(tokenProvider,userService), UsernamePasswordAuthenticationFilter.class)
            .addFilterBefore(new JwtExceptionFilter(handlerExceptionResolver), JwtAuthenticationFilter.class);
        return http.build();
    }
    
    ///api/user/send
    /// /api/refresh
    /// 
}