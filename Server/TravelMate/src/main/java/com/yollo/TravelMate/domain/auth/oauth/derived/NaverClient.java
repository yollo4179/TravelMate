package com.yollo.TravelMate.domain.auth.oauth.derived;



import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import com.yollo.TravelMate.domain.auth.oauth.base.OAuthClient;
import com.yollo.TravelMate.domain.auth.dto.external.OAuthExternalDto;
import com.yollo.TravelMate.domain.auth.dto.internal.UserInfo;


@Component
public class NaverClient implements OAuthClient {

	private final RestTemplate restTemplate = new RestTemplate();
	
	private final  String reqUrl = "https://openapi.naver.com/v1/nid/me";
	
	@Override
    public boolean supports(String provider) {
        return "NAVER".equalsIgnoreCase(provider);
    }
	
	@Override
    public UserInfo getInfo(String accessToken) {
	
	HttpHeaders headers = new HttpHeaders();
    headers.setBearerAuth(accessToken); 
    HttpEntity<String> entity = new HttpEntity<>(headers);
	
    ResponseEntity<OAuthExternalDto.Naver > response = restTemplate.exchange(
            reqUrl,
            HttpMethod.GET,
            entity,
            OAuthExternalDto.Naver.class
    );
    
    OAuthExternalDto.Naver dto = response.getBody();
    return new UserInfo(
            "NAVER",
            dto.response().id(),
            dto.response().email(),
            dto.response().nickname()
        );
    
	}
	
}
