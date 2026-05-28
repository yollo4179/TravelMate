package com.yollo.TravelMate.domain.user.dto.response;

import jakarta.validation.constraints.NotBlank;
import lombok.Builder;

public class UserResponseDto {
	@Builder
	public record AuthUserDto (
			 @NotBlank(message = "uid는 필수입니다.") String uid,
			 @NotBlank(message = "닉네임은 필수입니다.")String nickname,
			 String profileImgUrl,
			 @NotBlank(message = "유저 권한은 필수입니다.")String role,
			 String email // 선택
	){
		
	}
	
}
