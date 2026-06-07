package com.yollo.TravelMate.domain.user.controller;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.yollo.TravelMate.domain.auth.dto.internal.AuthLoginResultDto;
import com.yollo.TravelMate.domain.auth.dto.request.AuthRequestDto;
import com.yollo.TravelMate.domain.auth.dto.response.AuthResponseDto;
import com.yollo.TravelMate.domain.user.dto.request.UserRequestDto;

import com.yollo.TravelMate.domain.user.dto.response.UserResponseDto;
import com.yollo.TravelMate.domain.user.dto.response.UserResponseDto.AuthUserDto;
import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.service.UserServiceImpl;
import com.yollo.TravelMate.jwt.JwtTokenProvider;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;

/****************유저 `자원`을 관리합니다.**********************/

@RestController
@RequestMapping("/api/users") // 가이드라인의 기반 주소 설정
@RequiredArgsConstructor
public class UserController {

	
	private final UserServiceImpl userService;
	private final JwtTokenProvider tokenProvider;
	
	private static final Logger log = LoggerFactory.getLogger(UserController.class);
	
	
	
	@PostMapping("/checkUserId") 
	public ResponseEntity<?> checkUserId(@RequestBody @Valid UserRequestDto.CheckId request) {
	    userService.isUserIdDuplicated(request.userId());
	    return ResponseEntity.ok("사용 가능한 아이디 입니다.");
	}
	
	@PostMapping("/checkNickname") 
	public ResponseEntity<?> checkNickname(@RequestBody @Valid UserRequestDto.CheckNickname request) {
	    userService.isNicknameDuplicated(request.nickname());    
	    return ResponseEntity.ok("사용 가능한 닉네임입니다.");
	}
	
	@PostMapping("/signup")
    public ResponseEntity<String> signUp(@RequestBody @Valid UserRequestDto.Signup signupDto) {
        userService.signUp(signupDto);
        
        log.debug("${}",signupDto);
        return ResponseEntity.ok("회원가입이 완료되었습니다.");
    }
	
	@PostMapping("/signup/oauth")
    public ResponseEntity<AuthResponseDto.MobileLogin> signUpOauth(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String bearerToken, //임시토큰 입니다.
            @RequestBody @Valid AuthRequestDto.OAuthSignup signupDto) {
        
        if (bearerToken == null || !bearerToken.startsWith("Bearer ")) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }
        
        
        String tempToken = bearerToken.substring(7);
        AuthLoginResultDto result = userService.signupOauth(tempToken, signupDto);
        
        return ResponseEntity.ok(new AuthResponseDto.MobileLogin(
                false, 
                null, 
                result.getAccessToken(), 
                result.getRefreshToken()
        ));
    }
	
	@GetMapping("/me")
    public ResponseEntity<?> getUserProfile( 
    		@RequestHeader(HttpHeaders.AUTHORIZATION) String bearerToken
    ) {
		
		//베어러 토큰 처리
		 if (bearerToken != null && bearerToken.startsWith("Bearer ")) {
	            String accessToken = bearerToken.substring(7);
	            String uid = tokenProvider.getUIdFromToken(accessToken);     
	            UserResponseDto.AuthUserDto userProfileDto  =  userService.getUserProfile(uid);
	            return ResponseEntity.ok(userProfileDto);
		 }
		 return  ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("유효하지 않은 토큰입니다.");
    }
	
	@PutMapping("/me")//패스로식별은 x jwt보내면 필터가 뺏어가서 먼저 검증
    public ResponseEntity<String> updateUser(
            @AuthenticationPrincipal User user, //jwt 필터 거쳐서 user 가져옵
            @RequestBody @Valid UserRequestDto.Update updateDto) {
        // 현재 로그인한 유저의 고유 PK(uid)를 서비스로 전달
        userService.updateUser(user.getUid(), updateDto);
        return ResponseEntity.ok("회원 정보 수정이 완료되었습니다.");
    }
	
	
	
	@DeleteMapping("/me")
    public ResponseEntity<String> deleteUser(@AuthenticationPrincipal User user) {
        userService.deleteUser(user.getUid());
        return ResponseEntity.ok("회원 탈퇴가 완료되었습니다.");
    }
	
	
	
}
