package com.yollo.TravelMate.domain.user.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import java.util.UUID;

import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.yollo.TravelMate.domain.auth.dto.internal.AuthLoginResultDto;
import com.yollo.TravelMate.domain.auth.dto.request.AuthRequestDto;
import com.yollo.TravelMate.domain.user.dto.request.UserRequestDto;
import com.yollo.TravelMate.domain.user.dto.response.UserResponseDto;
import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.repository.UserRepository;
import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;
import com.yollo.TravelMate.jwt.JwtTokenProvider;
import com.yollo.TravelMate.redis.RedisService;

import io.jsonwebtoken.Claims;
import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService{
	
	
	private final UserRepository userRepository;

	private final JwtTokenProvider tokenProvider;
	
	private final PasswordEncoder passwordEncoder;
	
	
	private final RedisService redisService;
	
	private static final Logger log = LoggerFactory.getLogger(UserServiceImpl.class);
	

	
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
        
        
        if (userRepository.existsByUserId(signupDto.userId())) {
            throw new IllegalArgumentException("이미 존재하는 아이디입니다.");
        }
        
        if (userRepository.existsByEmail(signupDto.email())) {
            throw new IllegalArgumentException("이미 가입된 이메일입니다.");
        }

        if (userRepository.existsByNickname(signupDto.nickname())) {
            throw new IllegalArgumentException("이미 사용 중인 닉네임입니다.");
        }

       
        String encodedPassword = passwordEncoder.encode(signupDto.password());

        
        User user = signupDto.toEntity(encodedPassword);

        userRepository.save(user);
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

   
    
    @Override
    @Transactional(readOnly = true) // 데이터 변경이 없으므로 readOnly로 성능 최적화
    public UserResponseDto.AuthUserDto getUserProfile(String uid) {
        User user = userRepository.findByUid(uid)
                .orElseThrow(() -> new UsernameNotFoundException("해당 유저를 찾을 수 없습니다. UID: " + uid));

        return UserResponseDto.AuthUserDto.builder()
                .uid(user.getUid())
                .nickname(user.getNickname())
                .profileImgUrl(user.getProfileImgUrl())
                .role(user.getRole().toString()) 
                .email(user.getEmail())
                .build();
    }
	
    @Transactional
    public AuthLoginResultDto signupOauth(String tempToken, AuthRequestDto.OAuthSignup dto) {
    	
        if (!tokenProvider.validateToken(tempToken)) {
            throw new IllegalArgumentException("유효하지 않거나 만료된 임시 토큰입니다."); 
        }
        
        Claims claims = tokenProvider.getClaimsFromToken(tempToken);
        
        if (!"TEMP_REGISTER_TOKEN".equals(claims.getSubject())) {  //TEMP_REGISTER_TOKEN는 로그인 시도할 때 처음이라면 주는 임시 토큰의 subject..
            throw new IllegalArgumentException("회원가입용 임시 토큰이 아닙니다.");
        }
        String providerId = claims.get("providerId", String.class);
        String provider = claims.get("provider", String.class);
        String email = claims.get("email", String.class);
        
        // 이메일이 null일 경우 DB의 NOT NULL 제약조건을 피하기 위해 더미 이메일 생성
        if (email == null || email.isBlank()) {
            email = provider + "_" + providerId + "@social.com";
        }
        
        isNicknameDuplicated(dto.nickname());

        User newUser = User.builder()
                .uid(UUID.randomUUID().toString())
                .userId(provider + providerId.substring(8))
                .provider(provider)       
                .providerId(providerId)   
                .email(email)
                .nickname(dto.nickname())
                .role(JwtTokenProvider.ERole.USER.getValue())
                .status("ACTIVE")
                .build();
        
        userRepository.save(newUser);
        
        String accessToken = tokenProvider.createAccessToken(newUser.getUid(), newUser.getRole());
        String refreshToken = tokenProvider.createRefreshToken(newUser.getUid(), newUser.getRole());
        long rtTtlSeconds = tokenProvider.getRemainingTtlSeconds(refreshToken);
        redisService.saveRefreshToken(newUser.getUid(), refreshToken, rtTtlSeconds);
        
        return AuthLoginResultDto.builder()
                .accessToken(accessToken)
                .refreshToken(refreshToken)
                .rtTtlSeconds(rtTtlSeconds)
                .user(newUser).build();
    }
}
