package com.yollo.TravelMate.domain.user.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.repository.UserRepository;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService{
	@Autowired
	private final UserRepository userRepository;
	
	  // Spring Security에서 사용자 이름을 기반으로 정보를 가져오는 핵심 메서드
    @Override  public User loadUserByUsername(String username) throws UsernameNotFoundException {
     
        return userRepository.findByUid(username)
                .orElseThrow(() -> new UsernameNotFoundException("사용자를 찾을 수 없습니다: " + username));
    }
}
