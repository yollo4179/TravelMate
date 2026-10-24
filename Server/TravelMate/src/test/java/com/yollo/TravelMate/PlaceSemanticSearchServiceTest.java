package com.yollo.TravelMate;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import com.yollo.TravelMate.EmbeddingTest.EmbeddingTestParams;
import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.data.result.PlaceSemanticSearchResult;
import com.yollo.TravelMate.domain.place.repository.PlaceSemanticSearchRepository;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 더미 데이터 없이, 실제 DB에 쌓인 places(서울 관광지)를 대상으로
 * "임베딩 top-K 검색 -> 재랭킹" 전체 파이프라인(PlaceSemanticSearchService)을 그대로 돌려서 확인한다.
 * 선행 조건: TourPlaceRawCollectionServiceTest + TourPlaceIndexingServiceTest로 서울 관광지가
 * 이미 수집·가공되어 있어야 한다 (없으면 결과가 비어있거나 적을 수 있음).
 */
@SpringBootTest
class PlaceSemanticSearchServiceTest {

    @Autowired
    PlaceSemanticSearchService searchService;

    @Autowired
     PlaceSemanticSearchRepository repo;
    @Autowired
     EmbeddingClient embeddingClient;
    private static final Logger log = LoggerFactory.getLogger(PlaceSemanticSearchServiceTest.class);
    private static final String GREEN = "\u001B[32m";
     private static final String YELLOW = "\u001B[33m";
     private static final String RED = "\u001B[31m";
     private static final String RESET = "\u001B[0m";


    @Test
    void 종로_역사공부_실제_파이프라인_결과() {
        String query = "역사를 체험하고 배울 수 있는 장소";
        String city = "종로";


        List<EmbeddingTestParams> queries =
                List.of(

                        new EmbeddingTestParams(query, "", "")
                );

        queries.forEach(
                it -> {

                    String nowQuery = it.description();

                    float[] nowEmbedding = embeddingClient.embed(nowQuery);

                    log.info("{}=== 검색: {}==={}", RED, nowQuery, RESET);

                    repo.searchSimilar(nowEmbedding,null,  city, null, 0, 30)
                        .forEach((r) -> {
                            String similarity = String.format("%.4f", r.similarity());
                            log.info("{}{}->유사도: {}{}{}:city:{}:src:{}",
                                    RED, r.name(), GREEN, similarity, RESET, r.city(),
                                    r.tourContentId() != null ? "TourAPI" : "Kakao");
                        });
                });



        List<PlaceSemanticSearchResult> results = searchService.search(query, null, city, null, 10);
        System.out.println("=== 실제 파이프라인 결과 (query=\"" + query + "\", city=" + city + ") ===");
        for (PlaceSemanticSearchResult r : results) {
            System.out.printf("%.4f  %s (id=%d, tourContentId=%s)%n",
                    r.rerankScore(), r.place().name(), r.place().id(), r.place().tourContentId());
        }

        assertFalse(results.isEmpty(), "종로 지역에서 검색 결과가 없습니다 - 서울 관광지 수집/가공이 먼저 돼있어야 합니다");

        for (int i = 0; i < results.size() - 1; i++) {
            assertTrue(results.get(i).rerankScore() >= results.get(i + 1).rerankScore(),
                    "재랭킹 점수 내림차순 정렬이어야 함");
        }
    }
}
