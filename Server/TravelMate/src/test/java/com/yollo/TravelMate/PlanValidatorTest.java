package com.yollo.TravelMate;

import java.util.Set;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.validator.PlanValidator;

@SpringBootTest
public class PlanValidatorTest {

    @Autowired
    PlanValidator validator;

    @Test
    void 정상_JSON_파싱_검증() {
        String raw = """
                {
                  "planTitle": "가평 힐링 여행 일정",
                  "planDescription": "가평의 자연과 힐링을 즐기기 위한 여행",
                  "pins": [
                    {"placeId": 1898, "sequence": 1, "activity": "숙박", "reason": "편안한 휴식"},
                    {"placeId": 1870, "sequence": 2, "activity": "산책", "reason": "자연 감상"}
                  ]
                }
                """;
        // 검색 후보에 실제로 있던 id들
        Set<Long> validIds = Set.of(1898L, 1870L, 1848L, 1891L);

        GeneratedPlan plan = validator.validate(raw, validIds);
        System.out.println("제목: " + plan.planTitle());
        System.out.println("핀 개수: " + plan.pins().size());
        plan.pins().forEach(p ->
                System.out.println("  " + p.placeId() + " | " + p.activity()));
    }

    @Test
    void 코드블록_감싼_출력_정제() {
        String raw = """
                여기 플랜입니다!
```json
                {
                  "planTitle": "테스트",
                  "planDescription": "설명",
                  "pins": [{"placeId": 1898, "sequence": 1, "activity": "숙박", "reason": "휴식"}]
                }
```
                이대로 진행하세요.
                """;
        Set<Long> validIds = Set.of(1898L);

        GeneratedPlan plan = validator.validate(raw, validIds);
        System.out.println("코드블록+설명 제거 후 파싱: " + plan.planTitle());
        System.out.println("핀 개수: " + plan.pins().size());  // 1이면 정제 성공
    }

    @Test
    void 환각_placeId_제거() {
        String raw = """
                {
                  "planTitle": "환각 테스트",
                  "planDescription": "설명",
                  "pins": [
                    {"placeId": 1898, "sequence": 1, "activity": "숙박", "reason": "실재"},
                    {"placeId": 99999, "sequence": 2, "activity": "관광", "reason": "환각!"}
                  ]
                }
                """;
        Set<Long> validIds = Set.of(1898L);  // 99999는 후보에 없음

        GeneratedPlan plan = validator.validate(raw, validIds);
        System.out.println("환각 제거 후 핀 개수: " + plan.pins().size());  // 1이어야 함
        plan.pins().forEach(p -> System.out.println("  살아남은 id: " + p.placeId()));
        // 99999가 걸러지고 1898만 남으면 환각 차단 성공
    }
}
