package com.yollo.TravelMate.jwt;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;

@Getter
@Builder
@AllArgsConstructor
public class TokenResponseDto {
    private String grantType;    // 보통 "Bearer"라고 보냄
    private String accessToken;  // 실제 API 호출용 (가이드의 AT)
    private String refreshToken; // 재발급용 (가이드의 RT)
}