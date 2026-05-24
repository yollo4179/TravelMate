package com.yollo.TravelMate.domain.user.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.repository.UserRepository;
import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;
import com.yollo.TravelMate.jwt.TokenResponseDto;
import com.yollo.TravelMate.redis.RedisService;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService{
	
	
	private final UserRepository userRepository;

	private final com.yollo.TravelMate.jwt.JwtTokenProvider tokenProvider;
	
	private final PasswordEncoder passwordEncoder;
	
	
	private final RedisService redisService;
	
	private static final Logger log = LoggerFactory.getLogger(UserServiceImpl.class);
	
	@Transactional
    public TokenResponseDto login(UserRequestDto.Login loginDto) {
        User user = userRepository.findByUserId(loginDto.userId())
                .orElseThrow(() -> new IllegalArgumentException("가입되지 않은 이메일입니다."));

        if (!passwordEncoder.matches(loginDto.password(), user.getPassword())) {
            throw new IllegalArgumentException("비밀번호가 일치하지 않습니다.");
        }

        user.setStatus("ACTIVE");
    
        String accessToken = tokenProvider.createAccessToken(user.getUid(), user.getRole());
        String refreshToken = tokenProvider.createRefreshToken(user.getUid(), user.getRole());
        
        long rtTtlSeconds = tokenProvider.getRemainingTtlSeconds(refreshToken); 
        redisService.saveRefreshToken(user.getUserId(), refreshToken, rtTtlSeconds);
        // 토큰 발급 및 가이드 이미지의 1번 로직 수행
        return new TokenResponseDto(
        		accessToken,
        		refreshToken,
        		"Bearer"
        );
    }
	
	@Transactional //Transactional 애너테이션으로 인자로 받은 엔티티가 자동으로 엔티티 바꾸면 db 갱신 
    public void updateUser(String uid, UserRequestDto.Update updateDto) {
        User user = userRepository.findById(uid)
                .orElseThrow(() -> new UsernameNotFoundException("유저를 찾을 수 없습니다."));
        
        // 비밀번호 수정 요청이 있을 경우에만 암호화 로직 수행
        String password = user.getPassword();
        if (updateDto.password() != null && !updateDto.password().isEmpty()) {
            password = passwordEncoder.encode(updateDto.password());
        }

        // 엔티티의 updateProfile 메서드 활용
        user.updateProfile(updateDto.nickname(), updateDto.profileImgUrl());
        user.setPassword(password);
    }
	
	
	@Transactional // 데이터 변경이 일어나므로 쓰기 트랜잭션 적용
    public void signUp(UserRequestDto.Signup signupDto) {
        
        // 1. 중복 검증 (아이디 및 이메일)
        // 💡 record이므로 signupDto.userId(), signupDto.email()로 값을 꺼냅니다!
        if (userRepository.existsByUserId(signupDto.userId())) {
            throw new IllegalArgumentException("이미 존재하는 아이디입니다.");
        }
        
        if (userRepository.existsByEmail(signupDto.email())) {
            throw new IllegalArgumentException("이미 가입된 이메일입니다.");
        }

        if (userRepository.existsByNickname(signupDto.nickname())) {
            throw new IllegalArgumentException("이미 사용 중인 닉네임입니다.");
        }

        // 2. 비밀번호 암호화 (보안 필수)
        String encodedPassword = passwordEncoder.encode(signupDto.password());

        // 3. DTO를 엔티티로 변환 (우리가 만든 빌더 패턴 내부 호출 및 UUID 주입)
        User user = signupDto.toEntity(encodedPassword);

        // 4. DB에 최종 저장
        userRepository.save(user); //삽입이니까 더티체킹 관련없지?
    }

	@Transactional(readOnly=true)
	public boolean isUserIdDuplicated(String userId) {
		boolean exists = userRepository.existsByUserId(userId);
		if(exists) {
			throw new ErrorCodeException(ErrorCode.DUPLICATED_USER_ID);
		}
		
		return exists;
	}
	@Transactional (readOnly=true)
	public boolean isNicknameDuplicated(String nickname) {
		boolean exists = userRepository.existsByNickname(nickname);
		if(exists) {
			throw new ErrorCodeException(ErrorCode.DUPLICATED_NICKNAME);
		}
		return exists;
	}
	
	//인증
    @Override  public User loadUserByUsername(String userUid) throws UsernameNotFoundException {  
        return userRepository.findByUid(userUid)
                .orElseThrow(() -> new UsernameNotFoundException("사용자를 찾을 수 없습니다: " + userUid));
    }
    
    //회삭
    @Transactional
    public void deleteUser(String userUid) {
        User user = userRepository.findByUid(userUid)
                .orElseThrow(() -> new UsernameNotFoundException("유저를 찾을 수 없습니다."));
        
        userRepository.delete(user);
    }

   
    
    /*RTR 방식  Refresh +Access */
    @Transactional
    public TokenResponseDto refresh(String refreshToken) {
        // 1. Refresh Token 유효성 검증 (만료되었거나 변조되었는지 확인)
        if (!tokenProvider.validateToken(refreshToken)) {
            throw new IllegalArgumentException("유효하지 않거나 만료된 Refresh Token입니다. 다시 로그인해주세요.");
        }

       
        String userUid = tokenProvider.getUIdFromToken(refreshToken);

      
        User user = userRepository.findByUid(userUid)
                .orElseThrow(() -> new UsernameNotFoundException("사용자를 찾을 수 없습니다."));

        /*Redis에 새로 만든 토큰으로 갈아치우고 BlackList Token에 이전 토큰을 저장*/
        String savedRefreshToken = redisService.getRefreshToken(userUid);
        if (savedRefreshToken == null || !savedRefreshToken.equals(refreshToken)) {
            throw new IllegalArgumentException("변조되었거나 이미 로그아웃된 토큰입니다.");
        } 
        
        String newAccessToken = tokenProvider.createAccessToken(user.getUid(), user.getRole());
        String newRefreshToken = tokenProvider.createRefreshToken(user.getUid(), user.getRole());

      
        long newRtTtl = tokenProvider.getRemainingTtlSeconds(newRefreshToken);
        redisService.saveRefreshToken(user.getUserId(), newRefreshToken, newRtTtl);

        return new TokenResponseDto(newAccessToken, newRefreshToken, "Bearer");
    }
    

    
    
    @Transactional
    public  void logout(String userUid,String accessToken) {
    	 User user = userRepository.findByUid(userUid)
    			 .orElseThrow(() -> new UsernameNotFoundException("사용자를 찾을 수 없습니다: " + userUid));;
    	 user.setStatus("INACTIVE");
    			 
    	 /*여기서는 레디스에 토큰 지우고 클라에서는 토큰 지우는 로직 필요*/
    	 
    	 long atTtlSeconds = tokenProvider.getRemainingTtlSeconds(accessToken);
         redisService.logout(user.getUserId(), accessToken, atTtlSeconds);
    	 //Redis에 저장해 둔 Refresh 토큰을 지웁니다. 
    	// ex) refreshTokenRepository.deleteByUid(uid);
    	 log.debug("유저 UID :  ${} +  로그아웃 처리 완료 (DB에서 RT 삭제)",userUid);
    	 
    }

	


    
}
