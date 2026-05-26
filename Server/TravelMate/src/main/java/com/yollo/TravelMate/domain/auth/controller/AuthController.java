package com.yollo.TravelMate.domain.auth.controller;



import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.yollo.TravelMate.cookies.CookieUtil;
import com.yollo.TravelMate.domain.auth.service.AuthService;
import com.yollo.TravelMate.domain.user.dto.internal.AuthLoginResultDto;
import com.yollo.TravelMate.domain.user.dto.internal.AuthResultDto;
import com.yollo.TravelMate.domain.user.dto.request.UserRequestDto;
import com.yollo.TravelMate.domain.user.dto.response.TokenResponseDto;
import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.service.UserService;
import com.yollo.TravelMate.domain.user.service.UserServiceImpl;
import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;
import com.yollo.TravelMate.jwt.JwtTokenProvider;
import com.yollo.TravelMate.redis.RedisService;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;

@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {
	private final AuthService authService;
    private final CookieUtil cookieUtil ;
   private final JwtTokenProvider tokenProvider;
   private final RedisService redisService;
    
	private static final Logger log = LoggerFactory.getLogger(AuthController.class);
    @PostMapping("/login")
    public ResponseEntity<TokenResponseDto> login(@RequestBody @Valid UserRequestDto.Login loginDto) {
    		
    	
    	
    	AuthLoginResultDto result = authService.login(loginDto);
    		ResponseCookie rtCookie = cookieUtil.createRefreshTokenCookie(
                    result.getRefreshToken(), 
                    result.getRtTtlSeconds()
            );
    		User user = result.getUser();
    		TokenResponseDto bodyDto = TokenResponseDto.builder()
                    .accessToken(result.getAccessToken())
                    .uid(user.getUid())
                    .nickname(user.getNickname())
                    .profileImgUrl(user.getProfileImgUrl())
                    .role(user.getRole())
                    // .email(user.getEmail()) // 이메일도 필요하다면 추가
                    .build();
            
    		/*쿠키에 리프레시랑 엑세스 박습니다.*/
    		return ResponseEntity.ok()
                    .header(HttpHeaders.SET_COOKIE, rtCookie.toString())  //헤더에슨 httpOnly옵션으로 리프레시토큰
                    .body(bodyDto);
    }
    @PostMapping("/logout")
    public ResponseEntity<String> logout(
    		@RequestHeader(value = "Authorization", required = false) String bearerToken
    	){
    	
    	log.debug("ddd");
    	if (bearerToken == null) {
            return ResponseEntity.ok("이미 로그아웃된 상태입니다."); 
        }
    	
    	
    	String accessToken = bearerToken.startsWith("Bearer ") 
                ? bearerToken.substring(7) 
                : bearerToken;
    	
    	authService.logout(accessToken); 
        
        ResponseCookie emptyCookie = cookieUtil.createEmptyCookie();
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, emptyCookie.toString())
                .body("성공적으로 로그아웃 되었습니다.");
    }
    @PostMapping("/refresh")
    public ResponseEntity<TokenResponseDto> refresh(
            @CookieValue(value = "refreshToken", required = true) String refreshToken) {
        
    	/*리프레시 토큰 레디스 검증 or throw*/
        
      
        
    	/*쿠키(Cookie) 중 이름(키)이 refreshToken인 값을 찾아 메서드의 변수에 자동으로 넣어줌 httpOnly라도 클라에서 옵션 지정하면 넘겨 줌 */
        AuthResultDto result = authService.refresh(refreshToken);
        
        
        
        // 새 토큰으로 쿠키 덮어쓰기
        ResponseCookie rtCookie = cookieUtil.createRefreshTokenCookie(
                result.getRefreshToken(), 
                result.getRtTtlSeconds()
        );

        TokenResponseDto bodyDto = TokenResponseDto.builder()
                .accessToken(result.getAccessToken())
                .build();

        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, rtCookie.toString())
                .body(bodyDto);
    }
}
