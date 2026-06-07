package com.yollo.TravelMate.domain.auth.oauth.derived;

import java.util.Base64;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.auth.oauth.base.OAuthClient;
import com.yollo.TravelMate.domain.auth.dto.external.OAuthExternalDto;
import com.yollo.TravelMate.domain.auth.dto.internal.UserInfo;

@Component
public class GoogleClient implements OAuthClient {

    private final ObjectMapper objectMapper = new ObjectMapper();
  
	private static final Logger log = LoggerFactory.getLogger(GoogleClient.class);

    @Override
    public boolean supports(String provider) {
        return "GOOGLE".equalsIgnoreCase(provider);
    }

    //  구글 idToken 해독
    @Override
    public UserInfo getInfo(String idToken) {
        try {
            // 페이로드 부분 분리 및 Base64 디코딩 
        	// 헤더.페이로드.id
            String payload = idToken.split("\\.")[1];
            byte[] decodedBytes = Base64.getUrlDecoder().decode(payload);
            String payloadJson = new String(decodedBytes);
            OAuthExternalDto.Google dto = objectMapper.readValue(payloadJson, OAuthExternalDto.Google.class);
            log.debug(payloadJson);
          
            return new UserInfo(
                "GOOGLE",
                dto.sub(),      // 구글 고유 ID
                dto.email(),    // 구글 이메일
                dto.name()      // 구글 이름
            );

        } catch (JsonProcessingException | ArrayIndexOutOfBoundsException e) {
            throw new IllegalArgumentException("유효하지 않은 구글 토큰입니다.", e);
        }
    }
}