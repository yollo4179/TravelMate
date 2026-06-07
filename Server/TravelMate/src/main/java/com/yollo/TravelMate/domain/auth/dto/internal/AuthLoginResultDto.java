package com.yollo.TravelMate.domain.auth.dto.internal;

import com.yollo.TravelMate.domain.user.entity.User;
import lombok.Getter;
import lombok.experimental.SuperBuilder;

@Getter
@SuperBuilder
public class AuthLoginResultDto extends AuthResultDto {
	  private User user;
}
