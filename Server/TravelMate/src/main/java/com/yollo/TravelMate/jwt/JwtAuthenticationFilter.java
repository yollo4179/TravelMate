package com.yollo.TravelMate.jwt;

import java.io.IOException;

import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.apache.juli.logging.LogFactory;
import org.slf4j.*;
public class JwtAuthenticationFilter extends OncePerRequestFilter{

	

	private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);

	
	private final JwtTokenProvider tokenProvider ;
	public JwtAuthenticationFilter(JwtTokenProvider tokenProvider) {
		this.tokenProvider = tokenProvider;
	}
	

	@Override
	protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
			throws ServletException, IOException {
		//헤더에서 토큰 추출
		String token = tokenProvider.resolveToken(request);
		
		try {
            if (token != null && tokenProvider.validateToken(token)) {
                Authentication auth = tokenProvider.getAuthentication(token);
                //신분증'security가 이해할 수 있는 (Authentication 객체)을 만드는 작업입니다.
                
                SecurityContextHolder.getContext().setAuthentication(auth);
                //현재 실행 중인 스레드(요청 처리 과정)에 로그인 상태를 박아넣는 작업
                //현재 접속자의 정보를 보관하는 보관함: SecurityContextHolder
                log.debug("${}",auth);
            }
        } catch (ExpiredJwtException e) {
           // AT 기간 만료 (에러코드 40006)
            request.setAttribute("exception", "40006");
        } catch (JwtException e) {
            // 유효하지 않은 AT (에러코드 40007)
            request.setAttribute("exception", "40007");
        }

        filterChain.doFilter(request, response);
	}
	
	
}
