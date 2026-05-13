package com.yollo.TravelMate.domain.user.service;

import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

public class UserRequestDto {

	//회원 정보 수정 요청 DTO
	@Getter
	@NoArgsConstructor
	@AllArgsConstructor
	public static  class  Update {
	 private String nickname;
	 private String profileImgUrl;
	 private String password; // 비밀번호 변경 시 사용
	}

	
	// 로그인 요청
    @Getter
    @NoArgsConstructor(access = AccessLevel.PROTECTED)
    @AllArgsConstructor
    public static  class Login {
        private String email;
        private String password;
    }
    
    
	
}
