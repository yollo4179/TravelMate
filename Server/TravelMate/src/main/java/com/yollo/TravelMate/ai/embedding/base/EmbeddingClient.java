
package com.yollo.TravelMate.ai.embedding.base;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

public interface EmbeddingClient {

	float[] embed(String text);
	List<float[]> embedBatch(List<String> texts);//배치
	
	record EmbedRequest(List<String>texts)
	{	
		
	}
	
	record EmbedResponse(@JsonProperty("embeddings") List<List<Float>> embeddings)
	{}
}
