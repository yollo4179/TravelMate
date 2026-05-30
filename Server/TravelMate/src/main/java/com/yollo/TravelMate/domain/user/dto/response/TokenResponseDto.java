package com.yollo.TravelMate.domain.user.dto.response;

import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.annotation.JsonInclude;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;

@Getter
@Builder
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class TokenResponseDto {
	
    private String accessToken;  // 실제 API 호출용 (가이드의 AT)
    @Builder.Default 
    private String grantType= "Bearer "; ;// 보통 "Bearer"라고 보냄
    
    
 // Pinia 전역 상태 관리를 위한 유저 정보 추가
    private String uid;
    private String nickname;
    private String profileImgUrl;
    private String role;
    private String email;
    
}


