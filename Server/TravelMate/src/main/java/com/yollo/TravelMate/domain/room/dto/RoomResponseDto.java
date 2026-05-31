package com.yollo.TravelMate.domain.room.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import java.time.LocalDateTime;

public class RoomResponseDto {

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Detail {
        private Long roomId;
        private String title;
        private String description;
        private String category;
        private Boolean isPrivate;
        private String hostNickname;
        private LocalDateTime createdAt;
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Member {
        private String uid;
        private String nickname;
        private String profileImgUrl;
        private String roleAs;
        private String status;
    }
}
