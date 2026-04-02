package com.yollo.TravelMate.dto;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.LocalDate;
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
public class RoomPlanDTO {
	private Long roomPlanId;
    private Long roomId;
    private String title;
    private String content;
    private BigDecimal totalBudget;
    private LocalDate startDate;
    private LocalDate endDate;
    private LocalDateTime createdAt;

}
