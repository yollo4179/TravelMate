package com.yollo.TravelMate.domain.user.service;

import org.springframework.security.core.userdetails.UsernameNotFoundException;

import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.jwt.TokenResponseDto;



public interface UserService {
	


    // Spring Security에서 사용자 이름을 기반으로 정보를 가져오는 핵심 메서드
     public abstract User loadUserByUsername(String username) throws UsernameNotFoundException ;
     public abstract TokenResponseDto login(UserRequestDto.Login loginDto);
     
     public abstract void updateUser(String uid, UserRequestDto.Update updateDto) ;
     public void signUp(UserRequestDto.Signup signupDto);
     public abstract void deleteUser(String userUid);
     
     public abstract void logout(String userUid);
}
