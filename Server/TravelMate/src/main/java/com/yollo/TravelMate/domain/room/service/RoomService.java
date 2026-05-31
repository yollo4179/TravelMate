package com.yollo.TravelMate.domain.room.service;

import java.util.List;
import com.yollo.TravelMate.domain.room.dto.RoomRequestDto;
import com.yollo.TravelMate.domain.room.dto.RoomResponseDto;

public interface RoomService {
    RoomResponseDto.Detail createRoom(String hostUid, RoomRequestDto.Create createDto);
    void joinRoom(Long roomId, String userUid, RoomRequestDto.Join joinDto);
    void leaveRoom(Long roomId, String userUid);
    List<RoomResponseDto.Member> getRoomMembers(Long roomId);
    List<RoomResponseDto.Detail> getAllRooms();
}
