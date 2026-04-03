package com.yollo.TravelMate.domain.room.entity;
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
public class Room {

	private Long roomId;  			//PK
    private String title;			//title
    private String description;		//방 설명
    private String category;		//방의 카테고리
    private String pass;			//방 비번
    private Boolean isPrivate;		//방의 접근 권한
    private Long hostId;			//FK
    private LocalDateTime createdAt;
}
