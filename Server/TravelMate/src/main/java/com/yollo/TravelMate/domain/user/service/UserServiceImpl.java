package com.yollo.TravelMate.domain.user.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.repository.UserRepository;
import com.yollo.TravelMate.global.jwt.JwtTokenProvider;
import com.yollo.TravelMate.jwt.TokenResponseDto;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService{
	@Autowired
	private final UserRepository userRepository;
	@Autowired
	private final JwtTokenProvider tokenProvider;
	
	private final PasswordEncoder passwordEncoder;
	
	@Transactional
    public TokenResponseDto login(UserRequestDto.Login loginDto) {
        User user = userRepository.findByEmail(loginDto.getEmail())
                .orElseThrow(() -> new IllegalArgumentException("가입되지 않은 이메일입니다."));

        if (!passwordEncoder.matches(loginDto.getPassword(), user.getPassword())) {
            throw new IllegalArgumentException("비밀번호가 일치하지 않습니다.");
        }

        // 토큰 발급 및 가이드 이미지의 1번 로직 수행
        return new TokenResponseDto(
            tokenProvider.createAccessToken(user.getEmail(), user.getRole()),
            tokenProvider.createRefreshToken(user.getEmail())
        );
    }
	
	@Transactional
    public void updateUser(Long uid, UserRequestDto.Update updateDto) {
        User user = userRepository.findById(uid)
                .orElseThrow(() -> new UsernameNotFoundException("유저를 찾을 수 없습니다."));
        
        // 비밀번호 수정 요청이 있을 경우에만 암호화 로직 수행
        String password = user.getPassword();
        if (updateDto.getPassword() != null && !updateDto.getPassword().isEmpty()) {
            password = passwordEncoder.encode(updateDto.getPassword());
        }

        // 엔티티의 updateProfile 메서드 활용
        user.updateProfile(updateDto.getNickname(), updateDto.getProfileImgUrl());
        user.setPassword(password);
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
