package com.yollo.TravelMate.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import java.time.LocalDateTime;
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class UserDTO {
 
	private Long userId;
	private String email;
	private String password ; 
	private String nickname;
	private String phoneNumber; 
	private String profileImgUrl;
	private String role;
	private String status;
	private LocalDateTime createdAt;
	private LocalDateTime updatedAt;
	
}
