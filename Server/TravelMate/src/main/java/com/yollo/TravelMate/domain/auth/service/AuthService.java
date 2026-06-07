package com.yollo.TravelMate.domain.auth.service;

import com.yollo.TravelMate.domain.auth.dto.internal.AuthLoginResultDto;
import com.yollo.TravelMate.domain.auth.dto.internal.AuthResultDto;
import com.yollo.TravelMate.domain.auth.dto.request.AuthRequestDto;
import com.yollo.TravelMate.domain.auth.dto.response.AuthResponseDto;
import com.yollo.TravelMate.domain.user.dto.request.UserRequestDto;
import com.yollo.TravelMate.domain.user.dto.response.UserResponseDto;

public interface AuthService {
	 
	public abstract AuthLoginResultDto login(AuthRequestDto.LocalLogin loginDto);
	 public abstract AuthResponseDto.MobileLogin  oauthLogin(AuthRequestDto.SocialLogin loginDto);
     
	 public abstract void logout(String accessToken);
     public abstract AuthResultDto refresh(String refreshToken);
}
