package com.yollo.TravelMate.ai.rerank.derived;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.function.Function;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import com.yollo.TravelMate.ai.rerank.base.RerankClient;
import com.yollo.TravelMate.config.observability.SearchTracing;

import io.opentelemetry.api.trace.Span;

@Component
public class BgeRerankerClient implements RerankClient {

	private static final Logger logger = LoggerFactory.getLogger(BgeRerankerClient.class);

	private final RestClient restClient;

	// 임베딩 서버와 같은 프로세스(FastAPI)에 /rerank로 얹혀있음
	public BgeRerankerClient(
			@Value("${embedding.server.url:http://127.0.0.1:8000}") String baseUrl,
			SearchTracing searchTracing
	) {
		this.restClient = RestClient.builder()
				.baseUrl(baseUrl)
				.requestInterceptor(searchTracing.tracePropagationInterceptor())
				.build();
		this.searchTracing = searchTracing;
	}

	private final SearchTracing searchTracing;

	@Override
	public <T> List<Scored<T>> rerank(String query, List<T> candidates, Function<T, String> textOf) {
		List<String> texts = candidates.stream().map(textOf).toList();

		RerankResponse res = searchTracing.trace("reranking.http", () -> {
			Span.current().setAttribute("reranking.candidate_count", texts.size());
			return restClient
					.post()
					.uri("/rerank")
					.body(new RerankRequest(query, texts))
					.retrieve()
					.body(RerankResponse.class);
		});

		logger.debug("rerank 호출: query={}, 후보={}건", query, texts.size());

		if (res == null || res.scores() == null || res.scores().size() != candidates.size()) {
			throw new IllegalStateException(
					"재랭킹 서버 응답이 후보 수와 일치하지 않습니다. candidates=" + candidates.size()
							+ ", scores=" + (res == null ? "null" : res.scores()));
		}

		List<Scored<T>> scored = new ArrayList<>(candidates.size());
		for (int i = 0; i < candidates.size(); i++) {
			scored.add(new Scored<>(candidates.get(i), res.scores().get(i)));
		}
		scored.sort(Comparator.<Scored<T>>comparingDouble(Scored::score).reversed());
		return scored;
	}

	record RerankRequest(String query, List<String> texts) {}

	record RerankResponse(List<Float> scores) {}
}
