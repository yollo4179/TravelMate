package com.yollo.TravelMate.domain.session.entity;
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
public class RtcSession {
	private Long sessionId;
    private Long roomId;
    private String sessionKey;
    private LocalDateTime createdAt;
}
