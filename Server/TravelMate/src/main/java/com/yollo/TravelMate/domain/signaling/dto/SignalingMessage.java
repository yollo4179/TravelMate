package com.yollo.TravelMate.domain.signaling.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class SignalingMessage {
	private String type;
	private String senderId;
	private Object sdp;
	private Object candidate; 
}