package com.yollo.TravelMate.domain.room.dto;

import jakarta.validation.constraints.NotBlank;

public class RoomRequestDto {

    public record Create(
        @NotBlank(message = "방 제목은 필수입니다.") String title,
        String description,
        String category,
        String pass,
        Boolean isPrivate //프라이빗이 아니면 비번없이 아무나 접근가능
    ) {}

    public record Join(
        String pass
    ) {}
}
