package com.yollo.TravelMate.ai.llm.base;

import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

public final class LlmHttpClients {
    private LlmHttpClients() {}

    public static RestClient create(String baseUrl) {
        var requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(5000);
        requestFactory.setReadTimeout(240000);
        return RestClient.builder().baseUrl(baseUrl).requestFactory(requestFactory).build();
    }
}
