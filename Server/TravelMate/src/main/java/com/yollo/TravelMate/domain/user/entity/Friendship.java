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
	private Long friendshipId; //pk
	private String userId;	//fk
	private String friendId;	//fk
	private String status; // PENDING, ACCEPTED, REJECTED
	
	
}
