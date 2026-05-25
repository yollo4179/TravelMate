package com.yollo.TravelMate.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.messaging.simp.config.MessageBrokerRegistry;
import org.springframework.web.socket.config.annotation.EnableWebSocketMessageBroker;
import org.springframework.web.socket.config.annotation.StompEndpointRegistry;
import org.springframework.web.socket.config.annotation.WebSocketMessageBrokerConfigurer;


@Configuration
@EnableWebSocketMessageBroker
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer{

	
	@Override
    public void registerStompEndpoints(StompEndpointRegistry registry) {
        registry.addEndpoint("/ws-stomp")
        .setAllowedOriginPatterns("*") //CORS 패턴과 동일하게 프론트엔드의 [쿠키,인증] 통신을 허용
        .withSockJS(); // 웹소켓을 지원하지 않는 구형 브라우저를 위한 대체 옵션

	}
	@Override
    public void configureMessageBroker(MessageBrokerRegistry registry) {
        // 1. 메시지를 받을 때 (구독/소비)
        // 디스코드의 특정 방(채널)을 구독할 때의 접두사입니다. ex) /topic/group.1.channel.2
        registry.enableSimpleBroker("/topic"); //topic: 그룹 제목

        // 2. 메시지를 보낼 때 (발행/생성)
        // 클라이언트가 서버(컨트롤러)로 시그널링 데이터를 보낼 때의 접두사  ex) /app/signal
        registry.setApplicationDestinationPrefixes("/app");
    }
}