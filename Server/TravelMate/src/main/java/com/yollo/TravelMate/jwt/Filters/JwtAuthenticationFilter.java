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
	protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
			throws ServletException, IOException {
		
		
		String requestURI = request.getRequestURI();
		
		if (requestURI.equals("/api/login") || 
		        requestURI.equals("/api/signup") || 
		        requestURI.equals("/api/refresh") || 
		        requestURI.equals("/api/checkUserId") || 
		        requestURI.equals("/api/checkNickname")) {
		        filterChain.doFilter(request, response);
		        return;
		}
		
		//[엑세스 토큰 추출 :X-AUTH-TOKEN]
		String token = tokenProvider.resolveToken(request);
		
		if (token != null && tokenProvider.validateToken(token)) {
			//액세스 토큰 건재...
			Authentication auth = getAuthentication(token);
	        SecurityContextHolder.getContext().setAuthentication(auth);
	        log.debug("SecurityContext에 인증 정보 저장 완료: {}", auth);
		}
		filterChain.doFilter(request, response);
	}

	
	
	
}
