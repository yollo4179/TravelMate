package com.yollo.TravelMate.domain.auth.oauth.base;

import com.yollo.TravelMate.domain.auth.dto.internal.UserInfo;

public interface OAuthClient {
	public abstract boolean  supports(String provider); //프로바이더 필터 (리스트로 자식의 빈 3개 생성하고 필터로 가린다.)
	UserInfo getInfo(String idToken);
}
