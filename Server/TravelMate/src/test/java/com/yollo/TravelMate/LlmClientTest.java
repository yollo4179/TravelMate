package com.yollo.TravelMate;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import com.yollo.TravelMate.ai.llm.base.LlmClient;

@SpringBootTest
public class LlmClientTest {

	//LLM 여러개면 Factory에서 list로 bean을 받아서 조건에 맞는 llm 반환 처리( Factory를 빈으로 받아야함 )
    @Autowired
    LlmClient llmClient;

    @Test
    void 기본_생성_확인() {
//        String result = llmClient.generate(
//                "서울 당일치기 여행 계획을 JSON으로 만들어줘. "
//                + "장소 3곳, 각 장소는 name과 activity 필드만. JSON만 출력하고 설명 금지.");
//        System.out.println("=== LLM 응답 ===");
//        System.out.println(result);
    }
}