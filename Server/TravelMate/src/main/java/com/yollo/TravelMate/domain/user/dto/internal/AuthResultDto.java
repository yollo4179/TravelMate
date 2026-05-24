package com.yollo.TravelMate.domain.user.dto.internal;

import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public class AuthResultDto {
	private String accessToken;
    private String refreshToken;
    private long rtTtlSeconds;
}
