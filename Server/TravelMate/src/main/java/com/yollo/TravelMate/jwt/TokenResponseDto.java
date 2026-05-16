package com.yollo.TravelMate.jwt;

import org.springframework.transaction.annotation.Transactional;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;

@Getter
@Builder
@AllArgsConstructor
public class TokenResponseDto {
	
    private String accessToken;  // 실제 API 호출용 (가이드의 AT)
    private String refreshToken; // 재발급용 (가이드의 RT)
    @Builder.Default 
    private String grantType= "Bearer"; ;// 보통 "Bearer"라고 보냄
    
    
  
    
}