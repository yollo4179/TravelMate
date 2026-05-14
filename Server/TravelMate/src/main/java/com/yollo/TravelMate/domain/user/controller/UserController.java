package com.yollo.TravelMate.domain.user.controller;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
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
	
	@PostMapping("/login")
    public ResponseEntity<?> login(@RequestBody @Valid UserRequestDto.Login loginDto) {
        TokenResponseDto tokenResponse = userService.login(loginDto);
        return new  ResponseEntity<>(tokenResponse, HttpStatus.OK);
    }
	@PostMapping("/signup")
    public ResponseEntity<String> signUp(@RequestBody @Valid UserRequestDto.Signup signupDto) {
        userService.signUp(signupDto);
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
	
	
}
