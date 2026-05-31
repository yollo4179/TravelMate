package com.yollo.TravelMate.domain.room.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import com.yollo.TravelMate.domain.room.entity.Room;

@Repository
public interface RoomRepository extends JpaRepository<Room, Long> {
}
