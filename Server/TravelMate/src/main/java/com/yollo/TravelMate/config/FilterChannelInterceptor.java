package com.yollo.TravelMate.config;

import org.springframework.messaging.Message;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.ChannelInterceptor;
import org.springframework.messaging.support.MessageHeaderAccessor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.stereotype.Component;

import com.yollo.TravelMate.domain.user.service.UserService;
import com.yollo.TravelMate.jwt.JwtTokenProvider;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@Component
@RequiredArgsConstructor
public class FilterChannelInterceptor implements ChannelInterceptor {

    private final JwtTokenProvider tokenProvider;
    private final UserService userService;

    //채팅 + 방 구독하기 + 등 모든 preSend를 거쳐감
    @Override
    public Message<?> preSend(Message<?> message, MessageChannel channel) {
    	
        StompHeaderAccessor accessor = MessageHeaderAccessor.getAccessor(message, StompHeaderAccessor.class);

        // 클라에서 (`signaling`을 위한) STOMP 연결 요청(`CONNECT`) 시에만 인증 정보 검증 및 설정- 토큰 정보는 이미 건짐
        if (accessor != null && StompCommand.CONNECT.equals(accessor.getCommand())) { //onConnect 호출할때 meessage 확인
        	//최초로 연결(`CONNECT`)을 맺으려 할 때 딱 한 번만 인증을 수행 
        	//3way handshake는 할필요 없습니다.(브라우저랑 axios 통신하면서 이미 한번 함)
        	String bearerToken = accessor.getFirstNativeHeader("Authorization");
            
            log.info("[WebSocket CONNECT] Authorization Header: {}", bearerToken);

            
            if (bearerToken != null && bearerToken.startsWith("Bearer ")) {
                String token = bearerToken.substring(7);
                try {
                    if (tokenProvider.validateToken(token)) {
                        String uid = tokenProvider.getUIdFromToken(token);
                        UserDetails userDetails = userService.loadUserByUsername(uid);
                        
                        //Principal 등록
                        UsernamePasswordAuthenticationToken authentication = 
                                new UsernamePasswordAuthenticationToken(userDetails, "", userDetails.getAuthorities());
                        //accessor가 연결 시도 했으면 다시할 필요 없게 아예 세팅하기 토큰 만료되도 상관없음 한번 등록하면 끊길때까지..세션id로 처리
                        accessor.setUser(authentication);
                        
                        /*웹소켓 통로의 고유한 Session ID(예: session-123)
                         *  와 이 유저의 인증 정보(Principal) 를 서버 메모리
                         *  (SimpSession)에 단단히 묶어서(Mapping)*/
                        
                        log.info("[WebSocket CONNECT] 인증 성공 - User UID: {}", uid);
                    }
                } catch (Exception e) {
                    log.error("[WebSocket CONNECT] JWT Token Verification Failed: {}", e.getMessage());
                }
            } else {
                log.warn("[WebSocket CONNECT] No Bearer token found in STOMP headers");
            }
        }
        return message;
    }
}
