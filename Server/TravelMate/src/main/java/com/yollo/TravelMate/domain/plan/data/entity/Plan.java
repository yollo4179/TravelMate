package com.yollo.TravelMate.domain.plan.entity;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import java.time.LocalDateTime;
@Getter 
@Setter
@NoArgsConstructor 
@AllArgsConstructor
@Builder
public class Plan {
	private Long planId;
    private Long roomPlanId;
    private Long userId;
    private String title;
    private String description;
    private LocalDateTime createdAt;
}
