package com.yollo.TravelMate.domain.auth.dto.internal;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.experimental.SuperBuilder;

@Getter
@AllArgsConstructor
@SuperBuilder
public class AuthResultDto {
	
	protected String accessToken;
	protected String refreshToken;
	protected long rtTtlSeconds;
}
