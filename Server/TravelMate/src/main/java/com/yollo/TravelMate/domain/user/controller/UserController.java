package com.yollo.TravelMate.domain.user.controller;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.service.UserRequestDto;
import com.yollo.TravelMate.domain.user.service.UserServiceImpl;
import com.yollo.TravelMate.jwt.TokenResponseDto;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;



@RestController
@RequestMapping("/api") // 가이드라인의 기반 주소 설정
@RequiredArgsConstructor
public class UserController {

	
	private final UserServiceImpl userService;
	
	private static final Logger log = LoggerFactory.getLogger(UserController.class);
	
	
	@GetMapping("")
	public ResponseEntity<?> test(){
		 return new  ResponseEntity<>("test", HttpStatus.OK);
	}
	
	@PostMapping("/checkUserId") 
	public ResponseEntity<?> checkUserId(@RequestBody @Valid UserRequestDto.CheckId request) {
	    boolean isDuplicated = userService.isUserIdDuplicated(request.userId());
	    
	    if (isDuplicated) {
	        return ResponseEntity.status(HttpStatus.CONFLICT).body("이미 존재하는 아이디입니다.");
	    }
	    return ResponseEntity.ok().build();
	}
	
	@PostMapping("/checkNickname") 
	public ResponseEntity<?> checkNickname(@RequestBody @Valid UserRequestDto.CheckNickname request) {
	    boolean isDuplicated = userService.isNicknameDuplicated(request.nickname());
	    
	    if (isDuplicated) {
	        return ResponseEntity.status(HttpStatus.CONFLICT).body("이미 존재하는 닉네임입니다.");
	    }
	    return ResponseEntity.ok().build();
	}
	
	@PostMapping("/login")
    public ResponseEntity<?> login(@RequestBody @Valid UserRequestDto.Login loginDto) {
        TokenResponseDto tokenResponse = userService.login(loginDto);
        return new  ResponseEntity<>(tokenResponse, HttpStatus.OK);
    }
	@PostMapping("/signup")
    public ResponseEntity<String> signUp(@RequestBody @Valid UserRequestDto.Signup signupDto) {
        userService.signUp(signupDto);
        
        log.debug("${}",signupDto);
        return ResponseEntity.ok("회원가입이 완료되었습니다.");
    }
	
	@PutMapping("/user/update")//패스로식별은 x jwt ㅈ보내면 필터가 뺏어가서 먼저 검증
    public ResponseEntity<String> updateUser(
            @AuthenticationPrincipal User user, //jwt 필터 거쳐서 user 가져옵
            @RequestBody @Valid UserRequestDto.Update updateDto) {
        // 현재 로그인한 유저의 고유 PK(uid)를 서비스로 전달
        userService.updateUser(user.getUid(), updateDto);
        return ResponseEntity.ok("회원 정보 수정이 완료되었습니다.");
    }
	
	
	
	@DeleteMapping("/user/delete")
    public ResponseEntity<String> deleteUser(@AuthenticationPrincipal User user) {
        userService.deleteUser(user.getUid());
        return ResponseEntity.ok("회원 탈퇴가 완료되었습니다.");
    }
	
	
	//로그아웃 
    @PostMapping("/user/logout")
    public ResponseEntity<?> logout(@AuthenticationPrincipal User user){
    	userService.logout(user.getUid());
    	return ResponseEntity.ok("성공적으로 로그아웃 되었습니다.");
    }
    
    
    //Refresh로 액세스 발급
    @PostMapping("/refresh")
    public ResponseEntity<TokenResponseDto> refresh(@RequestBody Map<String, String> request) {
        String refreshToken = request.get("refreshToken");
        
        // 서비스에 재발급 로직을 위임하고 새 토큰 세트를 받음
        TokenResponseDto newTokenSet = userService.refresh(refreshToken);
        
        return ResponseEntity.ok(newTokenSet);
    }
	
}
