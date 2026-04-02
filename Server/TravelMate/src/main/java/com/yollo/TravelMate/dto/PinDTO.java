package com.yollo.TravelMate.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter 
@Setter
@NoArgsConstructor 
@AllArgsConstructor
@Builder
public class PinDTO {
	private Long pinId;
    private Long planId;
    private String placeName;
    private Double latitude;
    private Double longitude;
    private String memo;
    private Integer sequence;
    private BigDecimal cost;
    private LocalDateTime createdAt;
}
