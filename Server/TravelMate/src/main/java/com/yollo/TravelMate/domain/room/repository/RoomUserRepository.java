package com.yollo.TravelMate.domain.room.repository;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import com.yollo.TravelMate.domain.room.entity.RoomUser;

@Repository
public interface RoomUserRepository extends JpaRepository<RoomUser, Long> {
	List<RoomUser> findByRoomRoomId(Long roomId);
	Optional<RoomUser> findByRoomRoomIdAndUserUid(Long roomId, String uid);
	boolean existsByRoomRoomIdAndUserUid(Long roomId, String uid);
}
