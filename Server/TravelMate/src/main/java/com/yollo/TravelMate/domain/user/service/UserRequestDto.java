package com.yollo.TravelMate.domain.user.service;

import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import java.util.UUID;

import com.yollo.TravelMate.domain.user.entity.User;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
public class UserRequestDto {

	//회원 정보 수정 요청 DTO
	
	public record Update (
        @NotBlank(message = "닉네임은 필수입니다.") String nickname,
         String profileImgUrl,
        @NotBlank(message = "비밀번호는 필수입니다.")  String password // 비밀번호 변경 시 사용 (선택적)
    ) {}
	
	// 로그인 요청

    public record Login (
    	@NotBlank(message = "아이디는 필수입니다.") String userId,
        @NotBlank(message = "비밀번호는 필수입니다.") String password
    ) {	}
    //idCheck
    public record CheckId(
    		@NotBlank (message ="아이디는 필수입니다") String userId
    		) {}
    public record CheckNickname(
    		@NotBlank(message="닉네임은 필수입니다.")String nickname
    		) {}
    
    
    //nicknameCheck
    
    public record Signup(
            @NotBlank(message = "아이디는 필수입니다.") String userId,
            @NotBlank(message = "이메일은 필수입니다.") 
            @Email(message = "올바른 이메일 형식이 아닙니다.") String email,
            @NotBlank(message = "비밀번호는 필수입니다.") String password,
            @NotBlank(message = "닉네임은 필수입니다.") String nickname
        ) {
            public User toEntity(String encodedPassword) {
            	return User.builder()
                        .uid(UUID.randomUUID().toString()) // 스프링에서 UUID 생성하여 주입
                        .userId(this.userId)
                        .email(this.email)
                        .password(encodedPassword)
                        .nickname(this.nickname)
                        .role("ROLE_USER")
                        .status("INACTIVE")
                        .provider("LOCAL")
                        .build();
            	}
          }
    
    
        /* record */
    
	/*
	 *  Immutable(불변) 필드: 모든 필드에 자동으로 private final이 붙습니다.( 세터 x)
	 *  전체 생성자: 파라미터를 모두 받는 생성자가 자동으로 생성됩니다. (new SignupRequest("id", "email"))
	 *  Getter 메서드: 조금 특이한 점은 getUserId()가 아니라 필드명 그대로인 userId(), email()이라는 이름으로 Getter 메서드가 자동 생성됩니다.
	 *  표준 메서드 자동 구현: 객체 내부 값을 예쁘게 출력해 주는 toString(), 객체가 같은지 비교해 주는 equals()와 hashCode()가 알아서 구현됩니다.
	 * */
}
