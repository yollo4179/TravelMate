package com.yollo.TravelMate.util.managers;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import com.yollo.TravelMate.domain.auth.oauth.base.OAuthClient;
import com.yollo.TravelMate.domain.auth.dto.internal.UserInfo;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.Jwts;

@Component
public  class OauthManager {

	
	
	private final List<OAuthClient> oAuthClients;

    public OauthManager(List<OAuthClient> oAuthClients) {
        this.oAuthClients = oAuthClients;
    }

 
    public UserInfo getUserInfo(String provider, String token) {
        OAuthClient client = oAuthClients.stream()
                .filter(c -> c.supports(provider))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("지원하지 않는 소셜 플랫폼입니다: " + provider));

        
        return client.getInfo(token); 
    }
	
}
