package com.yollo.TravelMate.domain.user.service;

import org.springframework.security.core.userdetails.UsernameNotFoundException;

import com.yollo.TravelMate.domain.user.dto.request.UserRequestDto;
import com.yollo.TravelMate.domain.user.dto.response.UserResponseDto;
import com.yollo.TravelMate.domain.user.entity.User;



public interface UserService {
	


    // Spring Security에서 사용자 이름을 기반으로 정보를 가져오는 핵심 메서드
    
      
     
     public void signUp(UserRequestDto.Signup signupDto); 
     public abstract boolean isUserIdDuplicated(String userId);
     public abstract boolean isNicknameDuplicated(String nickname);
     
     
     public abstract void updateUser(String uid, UserRequestDto.Update updateDto) ;
     public abstract void deleteUser(String userUid); 
     
     public abstract User loadUserByUsername(String username) throws UsernameNotFoundException ;
     public UserResponseDto.AuthUserDto getUserProfile(String uid);
}
