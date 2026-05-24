package com.yollo.TravelMate.domain.user.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.yollo.TravelMate.domain.user.dto.internal.AuthResultDto;
import com.yollo.TravelMate.domain.user.dto.request.UserRequestDto;
import com.yollo.TravelMate.domain.user.dto.response.TokenResponseDto;
import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.repository.UserRepository;
import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;
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

   
    
   
	


    
}
