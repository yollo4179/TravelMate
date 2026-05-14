package com.yollo.TravelMate.domain.user.repository;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import com.yollo.TravelMate.domain.user.entity.User;

//JPA라는 비서에게 우리 DB 관리를 맡기는 계약서"
public interface UserRepository extends JpaRepository<User, String>{
	//User 엔티티와 연결된 users 테이블을 관리
	//String: "User 엔티티에서 **@Id(PK)**로 지정한 필드의 타입이 **string**이야."라고 알려
	Optional<User> findByEmail(String email);
	
	// 사용자 아이디(UID)로 사용자 찾기 (JWT 토큰에서 추출한 정보로 사용자 조회 시 사용)
    Optional<User> findByUid(String uid);
    
    boolean existsByUserId(String userId);
    boolean existsByEmail(String email);
    boolean existsByNickname(String nickname);
    
   
}
