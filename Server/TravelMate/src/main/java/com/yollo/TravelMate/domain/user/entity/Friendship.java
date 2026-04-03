package com.yollo.TravelMate.domain.user.entity;

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
public class Friendship {
	private long friendshipId; //pk
	private long userId;	//fk
	private long friendId;	//fk
	private String status; // PENDING, ACCEPTED, REJECTED
	
	
}
