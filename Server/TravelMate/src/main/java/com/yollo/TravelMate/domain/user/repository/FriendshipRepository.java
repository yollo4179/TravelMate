package com.yollo.TravelMate.domain.user.repository;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import com.yollo.TravelMate.domain.user.entity.Friendship;

@Repository
public interface FriendshipRepository extends JpaRepository<Friendship, Long> {
	List<Friendship> findByUserUid(String uid);
	Optional<Friendship> findByUserUidAndFriendUid(String uid, String friendUid);
	boolean existsByUserUidAndFriendUid(String uid, String friendUid);
}
