package com.yollo.TravelMate.dto;
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
public class RtcSessionDTO {
	private Long sessionId;
    private Long roomId;
    private String sessionKey;
    private LocalDateTime createdAt;
}
