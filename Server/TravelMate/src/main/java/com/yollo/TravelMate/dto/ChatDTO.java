package com.yollo.TravelMate.dto;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import java.time.LocalDateTime;
@Getter @Setter
@NoArgsConstructor @AllArgsConstructor
@Builder
public class ChatDTO {
	private Long chatId;			//PK
    private Long roomId;			//FK
    private Long userId;			//FK
    private String message;			//채팅 내용
    private LocalDateTime createdAt;
}
