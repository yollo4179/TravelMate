package com.yollo.TravelMate; // 본인 패키지 경로에 맞게 수정

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.RedisTemplate;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class RedisConnectionTest {

    @Autowired
    private RedisTemplate<String, Object> redisTemplate;

    @Test
    void 레디스_연결_및_데이터_저장_테스트() {
        // given (준비)
        String key = "test:travel:1";
        String value = "Gumi_Trip";

        // when (실행)
        redisTemplate.opsForValue().set(key, value);
        String result = (String) redisTemplate.opsForValue().get(key);

        // then (검증)
        System.out.println("=================================");
        System.out.println("Upstash에서 가져온 결과값: " + result);
        System.out.println("=================================");
        
        assertThat(result).isEqualTo(value);
    }
}