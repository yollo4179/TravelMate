package com.yollo.TravelMate.domain.signaling.controller;

import org.springframework.messaging.handler.annotation.DestinationVariable;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Controller;

import com.yollo.TravelMate.domain.signaling.dto.SignalingMessage;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

//stomp서버는 http api와 달리 MessageConverter가 직렬화 역직렬화 수행
//RestController는 안씀(HTTP Response Body에 담아 직접 반환 x)
//`연결된 세션을 유지`하며 `메시지 브로커`를 통한 `발행/구독`(Pub/Sub) 모델로 통신합
@Slf4j
@Controller
@RequiredArgsConstructor
public class SignalingController {
	private final SimpMessagingTemplate messagingTemplate;
	
	
	/*********Turn 서버*********************/
	/*해당 경로에 존재하는 모든 유저에게 sdp(통신 규격) 및 iceCandidate(모든 가능한 경로들의 모임)를 뿌립니다.*/
	@MessageMapping("/group/{groupId}/channel/{channelId}/signal")
    public void relaySignal(@DestinationVariable Long groupId,
                            @DestinationVariable Long channelId,
                            @Payload SignalingMessage message) {
        // 메시지가 발생한 특정 그룹의 특정 채널 구독자들에게만 데이터를 중계합니다.
        String destination = String.format("/topic/group/%d/channel/%d", groupId, channelId);
        
      
        // 전체 브로드캐스팅 후 프론트엔드에서 'sender' 값을 체크하여 본인 메시지면 무시하도록 처리하는 
        messagingTemplate.convertAndSend(destination, message);
        
        
        /**사설 IP로 연결이 안 되면 공인 IP(STUN)를 시도하고, 이마저도 방화벽에 막히면 최종적으로 중계 서버(TURN)를 이용합니다**/
    }
}
