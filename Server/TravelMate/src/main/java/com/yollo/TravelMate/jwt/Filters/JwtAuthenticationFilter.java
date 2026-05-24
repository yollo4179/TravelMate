package com.yollo.TravelMate.jwt.Filters;

import java.io.IOException;

import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.user.service.UserService;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorResponse;
import com.yollo.TravelMate.jwt.JwtTokenProvider;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;

import org.apache.juli.logging.LogFactory;
import org.slf4j.*;

@Component
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter{

	

	private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);

	private final JwtTokenProvider tokenProvider ;
	private final UserService userService;
	
	
	public Authentication getAuthentication(String token) {

		// UserDetails를 가져와서 시큐리티 인증 객체 생성
		UserDetails user = userService.loadUserByUsername(tokenProvider.getUIdFromToken(token));
		return new UsernamePasswordAuthenticationToken(user, "", user.getAuthorities());
		} 

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) throws ServletException {
	    String path = request.getRequestURI();
	    return path.equals("/api/auth/login") || 
	           path.equals("/api/auth/refresh") || 
	           path.equals("/api/users/signup") || 
	           path.equals("/api/users/checkUserId") || 
	           path.equals("/api/users/checkNickname");
	}
	
	@Override
	protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
			throws ServletException, IOException {
		
				
		
		System.out.println("\n========== [CCTV 가동] ==========");
	    System.out.println("1. 요청 URL: " + request.getRequestURI());
	            
	    // 토큰 추출
	    String token = tokenProvider.resolveToken(request);
	    System.out.println("2. 추출된 토큰: " + token);
	    
	    try {
	        if (token != null) {
	            boolean isValid = tokenProvider.validateToken(token);
	            System.out.println("3. 토큰 검증 통과 여부: " + isValid);
	            
	            if (isValid) {
	                Authentication auth = getAuthentication(token);
	                SecurityContextHolder.getContext().setAuthentication(auth);
	                System.out.println("4. [성공] 인증 객체 저장 완료: " + auth.getName());
	            }
	        } else {
	            System.out.println("3. [실패] 헤더에 토큰이 아예 없습니다.");
	        }
	    } catch (Exception e) {
	       
	        System.out.println("🚨 [에러 발생] 토큰 파싱/검증 중 예외 터짐: " + e.getClass().getSimpleName() + " - " + e.getMessage());
	    }
	    
	    System.out.println("=================================\n");
	    filterChain.doFilter(request, response);
	}

	
	
	
}
