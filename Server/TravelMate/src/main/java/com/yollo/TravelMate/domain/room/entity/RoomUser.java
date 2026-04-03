package com.yollo.TravelMate.domain.room.entity;

import java.time.LocalDateTime;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter 
@Setter
@NoArgsConstructor 
@AllArgsConstructor
@Builder
public class RoomUser {
	private Long participantId;  //PK
    private Long roomId;		//FK
    private Long userId;		//FK
    private String roleAs; // ADMIN, USER
    private String status; // ACTIVE, LEFT, BANNED
    private LocalDateTime joinedAt;
}
