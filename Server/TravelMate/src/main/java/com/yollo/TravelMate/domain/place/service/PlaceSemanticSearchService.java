package com.yollo.TravelMate.domain.place.service;

import java.util.List;

import org.springframework.stereotype.Service;

import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.ai.rerank.base.RerankClient;
import com.yollo.TravelMate.ai.rerank.base.RerankClient.Scored;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult;
import com.yollo.TravelMate.domain.place.repository.PlaceSemanticSearchRepository;

import lombok.RequiredArgsConstructor;

/**
 * 의미검색 2단계 파이프라인: 임베딩으로 top-K 후보를 넉넉히 뽑고, 그 레코드들을 그대로 재랭킹에 넘겨
 * 최종 상위 N개로 좁힌다. RETRIEVE_TOP_K가 limit보다 훨씬 커야 재랭킹이 순서를 뒤집을 여지가 생긴다
 * (bi-encoder 상위 few개만 뽑으면 애초에 재랭킹할 후보 자체가 부족해짐).
 */
@Service
@RequiredArgsConstructor
public class PlaceSemanticSearchService {

    private static final int RETRIEVE_TOP_K = 30;

    private final EmbeddingClient embeddingClient;
    private final PlaceSemanticSearchRepository placeSearchRepository;
    private final RerankClient rerankClient;

    public List<PlaceSemanticSearchResult> search(String query, String region, String city, String category, int limit) {
        if (query == null || query.isBlank()) {
            throw new IllegalArgumentException("검색어는 비어 있을 수 없습니다.");
        }
        if (limit < 1 || limit > RETRIEVE_TOP_K) {
            throw new IllegalArgumentException("검색 결과 개수는 1 이상 " + RETRIEVE_TOP_K + " 이하여야 합니다.");
        }

        float[] queryEmbedding = embeddingClient.embed(query);
        List<PlaceResult> candidates = placeSearchRepository.searchSimilar(
                queryEmbedding, region, city, category, 0.0, RETRIEVE_TOP_K);

        if (candidates.isEmpty()) {
            return List.of();
        }

        List<Scored<PlaceResult>> reranked = rerankClient.rerank(query, candidates, PlaceResult::description);

        return reranked.stream()
                .limit(limit)
                .map(scored -> new PlaceSemanticSearchResult(scored.candidate(), scored.score()))
                .toList();
    }
}
