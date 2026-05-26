package com.yollo.TravelMate.domain.auth.service;

import com.yollo.TravelMate.domain.user.dto.internal.AuthLoginResultDto;
import com.yollo.TravelMate.domain.user.dto.internal.AuthResultDto;
import com.yollo.TravelMate.domain.user.dto.request.UserRequestDto;

public interface AuthService {
	 public abstract AuthLoginResultDto login(UserRequestDto.Login loginDto);
     public abstract void logout(String accessToken);
     public abstract AuthResultDto refresh(String refreshToken);
}
