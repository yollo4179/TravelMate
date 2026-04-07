package com.yollo.TravelMate.domain.kakao.service;
import org.springframework.stereotype.Service;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;

import com.yollo.TravelMate.domain.kakao.dto.KakaoProfile;
import com.yollo.TravelMate.domain.room.entity.Room;
import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.repository.UserRepository;

import lombok.RequiredArgsConstructor;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.*; 
@Service
@RequiredArgsConstructor
public class KakaoService {


	private final UserRepository userRepository;
	
	// 유저가 카카오계정으로 로그인할 때 처리하는 로직 
	public void processLogin(String accessToken) {
		/*스프링이 외부api에 http요청을 보내기 위한 객체*/
	    RestTemplate rt2 = new RestTemplate();
	    /*유저가 로그인 할때, 카카오가 보내주는 인증(Bearer)토큰을 확인해야지만, 내부로직에 접근할 수 있다. */
	    HttpHeaders headers2 = new HttpHeaders();
	    headers2.add("Authorization", "Bearer " + accessToken); // 토큰 헤더 추가
	    headers2.add("Content-type", "application/x-www-form-urlencoded;charset=utf-8");

	    HttpEntity<MultiValueMap<String, String>> kakaoProfileRequest = 
	        new HttpEntity<>(headers2);

	    ResponseEntity<KakaoProfile> response2 = rt2.exchange(
	        "https://kapi.kakao.com/v2/user/me",
	        HttpMethod.POST,
	        kakaoProfileRequest,
	        KakaoProfile.class
	    );
	    KakaoProfile profile = response2.getBody();
	    if (profile == null) return ;
	    String email = profile.getKakao_account().getEmail();
	    String nickname = profile.getProperties().getNickname();
	    String profileImage = profile.getProperties().getProfile_image();
	    // 이미 가입된 유저라면 아무것도 수정하지 않고 
	    User user = userRepository.findByEmail(email).map(entity -> {
	    	        return entity; 
	    })
	    .orElseGet(() -> {
	    // DB에 없을 때(최초 1회)만 카카오 정보를 가져와서 가입시킴
	    	return User.builder()
	    			.email(email)
	    	        .nickname(nickname)
	    	        .profileImgUrl(profileImage)
	    	        .provider("KAKAO")
	    	        .status("ACTIVE")
	    	        .role("ROLE_USER")
	    	        .build();
	    	});
	    //영속성 : 레포지토리로 가져온 모델도 db에 저장하고 새로운 유저도 db에 저장-> 
	    userRepository.save(user);
	    //jwt 인증
        
	}
}
