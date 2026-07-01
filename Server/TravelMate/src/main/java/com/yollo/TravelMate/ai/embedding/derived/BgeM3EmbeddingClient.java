package com.yollo.TravelMate.ai.embedding.derived;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;

@Component
public class BgeM3EmbeddingClient implements EmbeddingClient{

	
	private static final Logger logger = LoggerFactory.getLogger(BgeM3EmbeddingClient.class);
	

    public BgeM3EmbeddingClient(
    		@Value("${embedding.server.url:http://127.0.0.1:8000}") String baseUrl) {
	        this.restClient = RestClient.builder().baseUrl(baseUrl).build();
	    }
	
	private final RestClient restClient;
	
	
	@Override
	public float[] embed(String text) {
		
		//임베딩은 "배치(Batch) 처리"가 표준(여러 문장을 한 번에)
		//"긴 글 임베딩: 텍스트가 여러 문맥으로 구성된 경우->내부적으로 여러 벡터를 반환할 수도 있다 -> pooling 단일 텍스트는 하나의 벡터 반환
		//문장 하나 - > 벡터 하나 완성-> [text]-> [features...] 1 개 
		//임베딩 모델이 self-attention으로 모든 문맥을 종합한 뒤 하나로 압축
		logger.debug("호출"+text);
		return embedBatch(List.of(text)).get(0);
	}

	@Override
	public List<float[]> embedBatch(List<String> texts) {
		EmbedResponse res = 
				restClient
				.post()
				.uri("/embed")
				.body(new EmbedRequest(texts))
				.retrieve() 
				.body(EmbedResponse.class);
		
		logger.info("Raw API Response: " + res);
		return res.embeddings().stream()
                .map(list -> {
                    float[] arr = new float[list.size()];
                    for (int i = 0; i < list.size(); i++) arr[i] = list.get(i);
                    return arr;
                })
                .toList();		
	}

}
