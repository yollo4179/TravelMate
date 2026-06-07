package com.yollo.TravelMate.domain.auth.service;

import java.util.Optional;

import org.slf4j.Logger;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.slf4j.LoggerFactory;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.password.PasswordEncoder;

import com.yollo.TravelMate.domain.auth.dto.internal.AuthLoginResultDto;
import com.yollo.TravelMate.domain.auth.dto.internal.AuthResultDto;
import com.yollo.TravelMate.domain.auth.dto.internal.UserInfo;
import com.yollo.TravelMate.domain.auth.dto.request.AuthRequestDto;
import com.yollo.TravelMate.domain.auth.dto.response.AuthResponseDto;
import com.yollo.TravelMate.domain.user.dto.request.UserRequestDto;
import com.yollo.TravelMate.domain.user.dto.response.UserResponseDto;
import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.repository.UserRepository;
import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;
import com.yollo.TravelMate.jwt.JwtTokenProvider;
import com.yollo.TravelMate.redis.RedisService;
import com.yollo.TravelMate.util.managers.OauthManager;

import lombok.RequiredArgsConstructor;


@Service
@RequiredArgsConstructor
public class AuthServiceImpl implements AuthService {

	
	private final OauthManager authManager;
	private final UserRepository userRepository;

	private final JwtTokenProvider tokenProvider;
	
	private final PasswordEncoder passwordEncoder;
	
	
	private final RedisService redisService;
	
	
	private static final Logger log = LoggerFactory.getLogger(AuthServiceImpl.class);
	
	
	
	
	
	
	/*RTR 방식  Refresh +Access */
    @Transactional
    public AuthResultDto refresh(String refreshToken) {
    	
    	log.debug( "리프레시 토큰입니다.${}",refreshToken);
        // 1. Refresh Token 유효성 검증 (만료되었거나 변조되었는지 확인)
        if (!tokenProvider.validateToken(refreshToken)) {
            throw new IllegalArgumentException("유효하지 않거나 만료된 Refresh Token입니다. 다시 로그인해주세요.");
        }
 
        String userUid = tokenProvider.getUIdFromToken(refreshToken);

      
        User user = userRepository.findByUid(userUid)
                .orElseThrow(() -> new UsernameNotFoundException("사용자를 찾을 수 없습니다."));

        /*Redis에 새로 만든 토큰으로 갈아치우고 BlackList Token에 이전 토큰을 저장*/
        String cachedToken = redisService.getRefreshToken(userUid);
        if (cachedToken == null || !cachedToken.equals(refreshToken)) {
        	throw new  ErrorCodeException(ErrorCode.USER_INVALID); //에러 메시지 -> 클라에서 처리
        } 
        
        String newAccessToken = tokenProvider.createAccessToken(user.getUid(), user.getRole());
        String newRefreshToken = tokenProvider.createRefreshToken(user.getUid(), user.getRole());

        /*이전 액세스 토큰 기한은 끝남 -> 블랙리스트에 등록할 필요*/
        long newRtTtl = tokenProvider.getRemainingTtlSeconds(newRefreshToken);
        redisService.saveRefreshToken(user.getUid(), newRefreshToken, newRtTtl);

        return new AuthResultDto(newAccessToken, newRefreshToken ,newRtTtl);
    }
    

    
    
    @Transactional
    public  void logout(String accessToken) {
    	 
    	
    	String targetUid = tokenProvider.getUidFromExpiredToken(accessToken);

        if (targetUid != null) {
        	User user = userRepository.findByUid(targetUid)
       			 .orElseThrow(() -> new UsernameNotFoundException("사용자를 찾을 수 없습니다: " + targetUid));
       	 user.setStatus("INACTIVE");    
       	/*여기서는 레디스에 토큰 지우고 클라에게 빈 토큰 줘서 지움*/
    	 long atTtlSeconds = tokenProvider.getRemainingTtlSeconds(accessToken);
         redisService.logout(targetUid, accessToken, atTtlSeconds);	
        	
        }
          
    }
    
    @Transactional
    public AuthLoginResultDto login(AuthRequestDto.LocalLogin loginDto) {
        User user = userRepository.findByUserId(loginDto.userId())
                .orElseThrow(() -> new IllegalArgumentException("가입되지 않은 이메일입니다."));

        if (!passwordEncoder.matches(loginDto.password(), user.getPassword())) {
            throw new IllegalArgumentException("비밀번호가 일치하지 않습니다.");
        }

        user.setStatus("ACTIVE");
    
        String accessToken = tokenProvider.createAccessToken(user.getUid(), user.getRole());
        String refreshToken = tokenProvider.createRefreshToken(user.getUid(), user.getRole());
        
        long rtTtlSeconds = tokenProvider.getRemainingTtlSeconds(refreshToken); 
        redisService.saveRefreshToken(user.getUid(), refreshToken, rtTtlSeconds);
      
        return  AuthLoginResultDto.builder()
        		.accessToken(accessToken)
        		.refreshToken(refreshToken)
        		.rtTtlSeconds(rtTtlSeconds)
        		.user(user).build();
        
    }
    
    @Transactional 
    public AuthResponseDto.MobileLogin oauthLogin(AuthRequestDto.SocialLogin loginDto) {
        
        
    	UserInfo userInfo = authManager.getUserInfo(loginDto.provider(), loginDto.idToken());
        log.debug("소셜에서 받아온 고유 ID: {}", userInfo.providerId());

        Optional<User> optionalUser = userRepository.findByProviderAndProviderId(
                loginDto.provider(), 
                userInfo.providerId()
        );

        if (optionalUser.isEmpty()) { //신규 회원입니다.
            String tempToken = "";
            try {
                tempToken = tokenProvider.createTempToken(userInfo.providerId(), loginDto.provider(), userInfo.email()); 
            } catch (Exception e) {
                e.printStackTrace();
            }

            return new AuthResponseDto.MobileLogin(true, tempToken, null, null); //닉네임제공 요청 

        } else {//기존 회원입니다.
            User user = optionalUser.get();
            String refreshToken = "";
            String accessToken = "";
            try {
            	refreshToken = tokenProvider.createRefreshToken(user.getUid().toString(), JwtTokenProvider.ERole.USER.getValue());
                accessToken = tokenProvider.createAccessToken(user.getUid().toString(), JwtTokenProvider.ERole.USER.getValue());
            } catch (Exception e) {
                e.printStackTrace();
            }

            return new AuthResponseDto.MobileLogin(false, null, accessToken, refreshToken); //이미 존재하는 유저입니다.
        }
    }
    
	private User registerNewUser(UserInfo userInfo ,String provider) { 
	        
	  
	        String nickname = userInfo.nickname();
	        if (nickname == null || nickname.isBlank()) {
	            nickname = provider +"_"+ java.util.UUID.randomUUID().toString().substring(0, 8);
	        }
	       
	        User newUser = User.builder()
	                .provider(userInfo.provider())       
	                .providerId(userInfo.providerId())   
	                .email(userInfo.email())
	                .nickname(nickname)
	                .build();
	        
	        return userRepository.save(newUser);
	    }
    
}
