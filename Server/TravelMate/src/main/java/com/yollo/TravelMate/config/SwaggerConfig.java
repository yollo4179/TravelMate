package com.yollo.TravelMate.config;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class SwaggerConfig {

    @Bean
    public OpenAPI openAPI() {
        return new OpenAPI()
                .info(new Info()
                        .title("Travel-Mate API 명세서")
                        .description("Signaling(사용자 매칭) 및 화상통화, 핀 동기화를 위한 백엔드 API입니다.")
                        .version("1.0.0"));
    }
}