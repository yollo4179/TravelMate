package com.yollo.TravelMate.domain.room.service;

import java.util.List;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.yollo.TravelMate.domain.room.dto.RoomRequestDto;
import com.yollo.TravelMate.domain.room.dto.RoomResponseDto;
import com.yollo.TravelMate.domain.room.entity.Room;
import com.yollo.TravelMate.domain.room.entity.RoomUser;
import com.yollo.TravelMate.domain.room.repository.RoomRepository;
import com.yollo.TravelMate.domain.room.repository.RoomUserRepository;
import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.repository.UserRepository;
import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;
import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
@Transactional 
public class RoomServiceImpl implements RoomService {

    private final RoomRepository roomRepository;
    private final RoomUserRepository roomUserRepository;
    private final UserRepository userRepository;

    @Override
    public RoomResponseDto.Detail createRoom(String hostUid, RoomRequestDto.Create createDto) {
        User host = userRepository.findByUid(hostUid)
                .orElseThrow(() -> new ErrorCodeException(ErrorCode.USER_NOT_FOUND));

        /* 방을 만들고 호스트 id + 방정보 세팅 */
        Room room = Room.builder()
                .title(createDto.title())
                .description(createDto.description())
                .category(createDto.category())
                .pass(createDto.pass())
                .isPrivate(createDto.isPrivate())
                .host(host)
                .build();

        /* 방을 db에 등록합니다. */
        Room savedRoom = roomRepository.save(room);

        
        /*방과 호스트를 이어주는 Utilty테이블을 작성합니다.*/
        RoomUser roomUser = RoomUser.builder()
                .room(savedRoom)
                .user(host)
                .roleAs("ADMIN")
                .status("ACTIVE")
                .build();
        roomUserRepository.save(roomUser);

        return mapToDetail(savedRoom);
    }

    @Override
    public void joinRoom(Long roomId, String userUid, RoomRequestDto.Join joinDto) {
        Room room = roomRepository.findById(roomId)
                .orElseThrow(() -> new ErrorCodeException(ErrorCode.ROOM_NOT_FOUND)); /*룸을 찾는다.*/
        
        User user = userRepository.findByUid(userUid)
                .orElseThrow(() -> new ErrorCodeException(ErrorCode.USER_NOT_FOUND)); /*user를 찾는다*/
        
        if (room.getIsPrivate() == Boolean.TRUE ) {
            if (room.getPass() != null && !room.getPass().equals(joinDto.pass())) {
                throw new ErrorCodeException(ErrorCode.INVALID_ROOM_PASSWORD);
                /*프라이 빗 룸인 경우 비밀 번호가 일치하는 지 확인한다. 아니면 알러트 날림*/
            }
        }
        
        
        
        boolean alreadyJoined = roomUserRepository.existsByRoomRoomIdAndUserUid(roomId, userUid);
        //해당 룸에 해당 유저가 이미 들어있나요???
        if (alreadyJoined)return ;
        
        //participants로 등록
        RoomUser roomUser = RoomUser.builder()
                    .room(room)
                    .user(user)
                    .roleAs("USER")
                    .status("ACTIVE")
                    .build();
        roomUserRepository.save(roomUser);
        
    }

    @Override
    public void leaveRoom(Long roomId, String userUid) {
        RoomUser roomUser = roomUserRepository.findByRoomRoomIdAndUserUid(roomId, userUid)
                .orElseThrow(() -> new ErrorCodeException(ErrorCode.ROOM_MEMBER_NOT_FOUND));
        /*Participants 그룸에서 제외합니다.-> 룸 삭제하면 영속성때문에 에러 날 것.. 
         * 룸 삭제시 RoomId에 있는 것들 다 지우고 수행*/
        roomUserRepository.delete(roomUser);
    }

    @Override
    @Transactional(readOnly = true)
    public List<RoomResponseDto.Member> getRoomMembers(Long roomId) {
        return roomUserRepository.findByRoomRoomId(roomId).stream()
                .map(ru -> RoomResponseDto.Member.builder()
                        .uid(ru.getUser().getUid())
                        .nickname(ru.getUser().getNickname())
                        .profileImgUrl(ru.getUser().getProfileImgUrl())
                        .roleAs(ru.getRoleAs())
                        .status(ru.getStatus())
                        .build())
                .collect(Collectors.toList()); // get All Participants
    }

    @Override
    @Transactional(readOnly = true)
    public List<RoomResponseDto.Detail> getAllRooms() {
        return roomRepository.findAll().stream()
                .map(this::mapToDetail) // ::Method- 매개변수 시그니처는 맞출 것 
                .collect(Collectors.toList()); // Room 2 Detail for response body
    }

    private RoomResponseDto.Detail mapToDetail(Room room) {
        return RoomResponseDto.Detail.builder()
                .roomId(room.getRoomId())
                .title(room.getTitle())
                .description(room.getDescription())
                .category(room.getCategory())
                .isPrivate(room.getIsPrivate())
                .hostNickname(room.getHost().getNickname())
                .createdAt(room.getCreatedAt())
                .build();
    }
}
