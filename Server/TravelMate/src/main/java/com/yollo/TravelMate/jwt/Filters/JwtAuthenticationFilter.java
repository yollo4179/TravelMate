package com.yollo.TravelMate.jwt.Filters;

import java.io.IOException;

import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
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
		/* 1. 필터에서 토큰 생성 시 user(UserDetails)를 첫 번째 인자(principal)로 지정 */
		return new UsernamePasswordAuthenticationToken(user, "", user.getAuthorities());
		} 

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) throws ServletException {
		
		//preFlight도 이 필터는 통과 시켜줘야함(cors터짐)
		if ("OPTIONS".equals(request.getMethod())) {
	        return true; 
	    }
		String path = request.getRequestURI();
	    return 
	    	   path.equals("/swagger-ui/**")|| 
	    	   path.equals("/v3/api-docs/**")|| 
	    	   path.equals("/swagger-ui.html")||
	    	   path.equals("/api/auth/login") || 
	    	   path.equals("/api/auth/login/oauth")||
	           path.equals("/api/auth/refresh") || 
	           path.equals("/api/users/signup") || 
	           path.equals("/api/users/signup/oauth") || 
	           path.equals("/api/users/checkUserId") || 
	           path.equals("/api/users/checkNickname") ||
	           path.startsWith("/ws-stomp") || 
	           //Socket 통신을 위해서는 3way handshake 필요함 stomp 연결시도는
	           //http request가 아니므로 여기서 뚫어주고 뒤에서 토큰 받도록해서 stomp 소켓이랑 해서 연결 시도 
	           path.equals("/error");
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
	            	 // DB 조회를 거친 인증 정보를 받아와 보관소(SecurityContextHolder)에 넣습니다.
	            	Authentication auth = getAuthentication(token);
	            	
	            	
	            	SecurityContextHolder.getContext().setAuthentication(auth);
	            	/* 2. 이 인증 객체(principal)를 스프링 보관함에 보관 
	            	 * @AuthenticationPrincipal으로 헤더에 액세스 or refresh 토큰을 보냈다면 유저정보 받아올 수 있습니다.
	            	 * 아님 말구...
	            	 * */
	            	//AuthorizeFilter(마지막 관문)에게 허용되기 위해 Authentication 세팅 
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
