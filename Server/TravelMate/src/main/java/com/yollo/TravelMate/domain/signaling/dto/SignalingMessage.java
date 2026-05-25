package com.yollo.TravelMate.domain.signaling.dto;

import lombok.RequiredArgsConstructor;

@RequiredArgsConstructor
public class SignalingMessage {
	private String type;
	private String senderId;
	private Object sdp;
	private Object candidate; 
	
	// 메시지를 보낸 유저 UID
	// Offer나 Answer의 Session Description Protocol `데이터`
	// ICE Candidate 네트워크 경로 데이터
}