package com.yollo.TravelMate.domain.auth.oauth.derived;

import java.util.Base64;

import org.springframework.stereotype.Component;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.auth.oauth.base.OAuthClient;
import com.yollo.TravelMate.domain.auth.dto.external.OAuthExternalDto;
import com.yollo.TravelMate.domain.auth.dto.internal.UserInfo;

@Component
public class KakaoClient implements OAuthClient {

	
	

        private final ObjectMapper objectMapper = new ObjectMapper();

        
        @Override
        public boolean supports(String provider) {
            return "KAKAO".equalsIgnoreCase(provider);
        }

        
        @Override
        public UserInfo getInfo(String idToken) {
            
            try {
                
                String payload = idToken.split("\\.")[1];

              
                byte[] decodedBytes = Base64.getUrlDecoder().decode(payload);
                String payloadJson = new String(decodedBytes);

                OAuthExternalDto.Kakao dto = objectMapper.readValue(payloadJson, OAuthExternalDto.Kakao.class);

            
                return new UserInfo(
                    "KAKAO",
                    dto.sub(),      // 카카오 고유 ID (필수)
                    dto.email(),    // 이메일 (권한 있을 경우)
                    null            // 카카오 idToken에는 보통 닉네임이 없으므로 null 처리
                );

            } catch (JsonProcessingException | ArrayIndexOutOfBoundsException e)  {
                throw new IllegalArgumentException("유효하지 않은 카카오 토큰입니다.", e);
            }
        }

}
