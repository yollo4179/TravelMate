package com.yollo.TravelMate.domain.room.controller;

import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import com.yollo.TravelMate.domain.room.dto.RoomRequestDto;
import com.yollo.TravelMate.domain.room.dto.RoomResponseDto;
import com.yollo.TravelMate.domain.room.service.RoomService;
import com.yollo.TravelMate.domain.user.entity.User;

import io.swagger.v3.oas.annotations.Operation;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;

@RestController
@RequestMapping("/api/rooms")
@RequiredArgsConstructor
public class RoomController {

    private final RoomService roomService;

    @Operation(summary = "사용자가 방 생성하기", description = "사용자가 클라이언트로부터 방의 상세 정보를 넘겨주면"
    		+ "사용자를 호스트로 하는 방을 생성하고, 호스트 자신도 Participants(RoomUser)로 등록합니다. ")
    @PostMapping
    public ResponseEntity<RoomResponseDto.Detail> createRoom(
            @AuthenticationPrincipal User user,
            @RequestBody @Valid RoomRequestDto.Create createDto) { //방제, 방 설명, 카테고리 , 비번 , 공개 유무
    	
    	
        RoomResponseDto.Detail detail = roomService.createRoom(user.getUid(), createDto); //호스트 정보(나) +방 정보
        return ResponseEntity.ok(detail);
    }
    
    
    @Operation(summary = "모든 룸 목록을 가져오기", description = "룸 테이블의 모든 목록을 가져옵니다.")
    @GetMapping
    public ResponseEntity<List<RoomResponseDto.Detail>> getAllRooms() {
        List<RoomResponseDto.Detail> rooms = roomService.getAllRooms();
        return ResponseEntity.ok(rooms);
    }
    @Operation(summary = "방에 참가( + Signaling을 통한 p2p 연결)", description = "사용자를 원하는 방에 참여시키고 대화를 할 수 있도록 Signaling을 진행합니다.")
    @PostMapping("/{roomId}/join")
    public ResponseEntity<String> joinRoom(
            @PathVariable Long roomId, //RoomId
            @AuthenticationPrincipal User user, // 나
            @RequestBody(required = false) RoomRequestDto.Join joinDto) { //password 
    	
    	
        RoomRequestDto.Join requestJoinDto = joinDto != null ? joinDto : new RoomRequestDto.Join(null); 
        /*비번 침 : 안침*/
        roomService.joinRoom(roomId, user.getUid(), requestJoinDto);
        return ResponseEntity.ok("방에 성공적으로 참가했습니다.");
    }
    @Operation(summary = "방 탈출", description = "사용자를 참여 중인 방을 나갑니다.- roomuser table에서 레코드 제거")
    @PostMapping("/{roomId}/leave")
    public ResponseEntity<String> leaveRoom(
            @PathVariable Long roomId,
            @AuthenticationPrincipal User user) {
        roomService.leaveRoom(roomId, user.getUid());
        return ResponseEntity.ok("방을 성공적으로 퇴장했습니다.");
    }
    @Operation(summary = "멤버 정보 가져오기.", description = "(signaling 정보는 아닙니다.)방에 참여하고 있는 모든 유저의 정보를 가져옵니다.")
    @GetMapping("/{roomId}/members")
    public ResponseEntity<List<RoomResponseDto.Member>> getRoomMembers(
            @PathVariable Long roomId) {
        List<RoomResponseDto.Member> members = roomService.getRoomMembers(roomId);
        return ResponseEntity.ok(members);
    }
}
