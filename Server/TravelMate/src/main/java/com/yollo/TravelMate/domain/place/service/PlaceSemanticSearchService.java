package com.yollo.TravelMate.domain.place.service;

import java.util.List;

import org.springframework.stereotype.Service;

import com.yollo.TravelMate.domain.place.client.PlaceSemanticSearchClient;
import com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class PlaceSemanticSearchService {

    public enum RankingMode {
        RERANKED,
        SEMANTIC_ONLY
    }

    private static final int MAX_SEARCH_LIMIT = 30;

    private final PlaceSemanticSearchClient placeSemanticSearchClient;

    public List<PlaceSemanticSearchResult> search(
            String query,
            String region,
            String city,
            String category,
            int limit
    ) {
        return search(query, region, city, category, limit, null, RankingMode.RERANKED);
    }

    public List<PlaceSemanticSearchResult> search(
            String query,
            String region,
            String city,
            String category,
            int limit,
            PlanContext.Area area
    ) {
        return search(query, region, city, category, limit, area, RankingMode.RERANKED);
    }

    public List<PlaceSemanticSearchResult> search(
            String query,
            String region,
            String city,
            String category,
            int limit,
            PlanContext.Area area,
            RankingMode rankingMode
    ) {
        if (query == null || query.isBlank()) {
            throw new IllegalArgumentException("검색어는 비어 있을 수 없습니다.");
        }
        if (limit < 1 || limit > MAX_SEARCH_LIMIT) {
            throw new IllegalArgumentException("검색 결과 수는 1 이상 " + MAX_SEARCH_LIMIT + " 이하여야 합니다.");
        }
        return placeSemanticSearchClient.search(query, region, city, category, limit, area, rankingMode);
    }
}
