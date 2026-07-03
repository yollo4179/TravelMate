package com.yollo.TravelMate;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import com.yollo.TravelMate.domain.plan.service.PlanGenerationService;

@SpringBootTest
public class PlanGenerationTest {

    @Autowired
    PlanGenerationService planService;

    @Test
    void 후보기반_플랜생성() {
        String result = planService.generatePlanRaw("가평 힐링 여행", "경기");
        System.out.println("=== 생성된 플랜 ===");
        System.out.println(result);
    }
    
    @Test
    void 플랜_생성_저장_전체흐름_END_TO_END() {
    	Long planId = planService.generateAndSave(
                "가평 힐링 여행",
                "경기",
                "f28ae363-af07-424e-a14b-00e217124f0d");  // ← 실제 uid
        System.out.println("저장된 planId: " + planId);
    }
}