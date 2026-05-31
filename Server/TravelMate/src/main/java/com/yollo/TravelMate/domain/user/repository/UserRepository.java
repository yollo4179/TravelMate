package com.yollo.TravelMate.domain.user.repository;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

import com.yollo.TravelMate.domain.user.dto.response.UserResponseDto;
import com.yollo.TravelMate.domain.user.entity.User;

//JPA라는 비서에게 우리 DB 관리를 맡기는 계약서"
public interface UserRepository extends JpaRepository<User, String>{
	
	Optional<User> findByEmail(String email);
	Optional<User> findByUserId(String userId);
	
    Optional<User> findByUid(String uid);
    
    boolean existsByUserId(String userId);
    boolean existsByEmail(String email);
    boolean existsByNickname(String nickname);
    
    
}
