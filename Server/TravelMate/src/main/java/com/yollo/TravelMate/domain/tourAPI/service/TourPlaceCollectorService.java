package com.yollo.TravelMate.domain.tourAPI.service;

import java.util.ArrayList;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.repository.PlaceVectorRepository;
import com.yollo.TravelMate.domain.place.repository.PlaceVectorRepository.PlaceInsert;
import com.yollo.TravelMate.domain.tourAPI.client.TourApiDetailClient;
import com.yollo.TravelMate.domain.tourAPI.client.TourApiDetailClient.TourApiCommonResult;
import com.yollo.TravelMate.domain.tourAPI.client.TourApiDetailClient.TourApiInfoItem;
import com.yollo.TravelMate.domain.tourAPI.client.TourApiListClient;
import com.yollo.TravelMate.domain.tourAPI.client.TourApiListClient.TourApiListItem;
import com.yollo.TravelMate.domain.tourAPI.client.TourApiListClient.TourApiListPage;
import com.yollo.TravelMate.domain.tourAPI.enums.TourAreaCode;
import com.yollo.TravelMate.domain.tourAPI.enums.TourContentType;
import com.yollo.TravelMate.domain.tourAPI.repository.PlaceDetailRepository;
import com.yollo.TravelMate.domain.tourAPI.repository.PlaceDetailRepository.ProgramInsert;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class TourPlaceCollectorService {

    private static final Logger log = LoggerFactory.getLogger(TourPlaceCollectorService.class);

    private final TourApiListClient listClient;
    private final TourApiDetailClient detailClient;
    private final EmbeddingClient embeddingClient;
    private final PlaceVectorRepository placeRepository;
    private final PlaceDetailRepository placeDetailRepository;

    private static final int NUM_OF_ROWS = 100;
    private static final int BATCH_SIZE = 64;
    private static final int MAX_FLUSH_FAILURES = 3;
    private int consecutiveFlushFailures = 0;

    public void healthCheck() {
        try {
            embeddingClient.embed("health check");
        } catch (Exception e) {
            throw new IllegalStateException(
                    "임베딩 서버 연결 불가. 수집을 중단합니다. FastAPI(8000) 먼저 실행하세요.", e);
        }
    }

    public CollectResult collectAll(List<TourAreaCode> areaFilter, List<TourContentType> typeFilter) {
        healthCheck();

        int searched = 0, inserted = 0, skippedNoOverview = 0;

        List<TourAreaCode> areas = (areaFilter != null) ? areaFilter : List.of(TourAreaCode.values());
        List<TourContentType> types = (typeFilter != null) ? typeFilter : List.of(TourContentType.values());

        List<Candidate> buffer = new ArrayList<>();

        for (TourAreaCode area : areas) {
            for (TourContentType type : types) {

                TourApiListPage firstPage = listClient.fetchPage(
                        area.getAreaCode(), type.getContentTypeId(), NUM_OF_ROWS, 1);

                int totalCount = firstPage.totalCount();
                if (totalCount == 0) {
                    log.info("[{} - {}] 결과 없음", area.getRegion(), type.getLabel());
                    continue;
                }

                int totalPages = (int) Math.ceil((double) totalCount / NUM_OF_ROWS);
                log.info("[{} - {}] 총 {}건, {}페이지 수집 시작",
                        area.getRegion(), type.getLabel(), totalCount, totalPages);

                for (int page = 1; page <= totalPages; page++) {
                    TourApiListPage listPage = (page == 1)
                            ? firstPage
                            : listClient.fetchPage(area.getAreaCode(), type.getContentTypeId(), NUM_OF_ROWS, page);

                    for (TourApiListItem item : listPage.items()) {
                        searched++;
                        if (item.contentId() == null) continue;

                        if (placeRepository.existsByTourContentId(item.contentId())) {
                            continue;
                        }

                        // 공통정보 조회 (overview + homepage + firstimage)
                        TourApiCommonResult common = detailClient.fetchCommon(item.contentId());

                        // 체험 프로그램 (detailInfo2)
                        List<TourApiInfoItem> infoItems =
                                detailClient.fetchInfoItems(item.contentId(), item.contentTypeId());

                        // description = overview + 프로그램 텍스트
                        String description = buildDescription(common.overview(), infoItems);

                        if (common.overview() == null) {
                            skippedNoOverview++;
                        }

                        buffer.add(new Candidate(item, common, area, type, description, infoItems));

                        if (buffer.size() >= BATCH_SIZE) {
                            inserted += flush(buffer);
                        }
                    }
                }
            }
        }

        if (!buffer.isEmpty()) {
            inserted += flush(buffer);
        }

        return new CollectResult(searched, inserted, skippedNoOverview);
    }

    private int flush(List<Candidate> buffer) {
        List<Integer> embedTargetIdx = new ArrayList<>();
        List<String> textsToEmbed = new ArrayList<>();
        for (int i = 0; i < buffer.size(); i++) {
            Candidate c = buffer.get(i);
            if (c.common().overview() != null) {
                embedTargetIdx.add(i);
                textsToEmbed.add(c.item().title() + ". " + c.description());
            }
        }

        List<float[]> embeddings = List.of();
        if (!textsToEmbed.isEmpty()) {
            try {
                embeddings = embeddingClient.embedBatch(textsToEmbed);
                consecutiveFlushFailures = 0;
            } catch (Exception e) {
                if (++consecutiveFlushFailures >= MAX_FLUSH_FAILURES) {
                    throw new IllegalStateException(
                            "임베딩 서버 연속 " + MAX_FLUSH_FAILURES + "회 실패 - 수집 중단", e);
                }
                log.error("배치 임베딩 실패 ({}건) - 이 배치 건너뜀: {}", textsToEmbed.size(), e.getMessage());
                buffer.clear();
                return 0;
            }
        }

        float[][] embByBufferIdx = new float[buffer.size()][];
        for (int j = 0; j < embedTargetIdx.size(); j++) {
            embByBufferIdx[embedTargetIdx.get(j)] = embeddings.get(j);
        }

        List<PlaceInsert> inserts = new ArrayList<>(buffer.size());
        for (int i = 0; i < buffer.size(); i++) {
            Candidate c = buffer.get(i);
            inserts.add(new PlaceInsert(
                    c.item().title(),
                    c.description(),
                    c.area().getRegion(),
                    extractCity(c.item().addr1()),
                    c.type().getLabel(),
                    "tourapi",
                    c.item().mapY(),                    // latitude
                    c.item().mapX(),                    // longitude
                    null,                                // kakaoPlaceId
                    c.item().contentId(),
                    c.item().contentTypeId(),
                    c.item().imageUrl(),                 // 목록 단계 firstimage (그대로 사용)
                    c.common().homepageUrl(),            // ← 상세(detailCommon2)에서 얻은 homepage
                    embByBufferIdx[i]
            ));
        }
        placeRepository.insertTourApiPlaceBatch(inserts);

        saveProgramsForBatch(buffer);

        int n = buffer.size();
        buffer.clear();
        log.info("배치 적재 {}건", n);
        return n;
    }

    private void saveProgramsForBatch(List<Candidate> buffer) {
        for (Candidate c : buffer) {
            if (c.infoItems().isEmpty()) continue;

            Long placeId = placeRepository.findIdByTourContentId(c.item().contentId());
            if (placeId == null) continue;

            List<ProgramInsert> programs = c.infoItems().stream()
                    .map(i -> new ProgramInsert(i.infoName(), i.infoText(), i.serialNum()))
                    .toList();
            placeDetailRepository.replaceProgramItems(placeId, programs);
        }
    }

    private String buildDescription(String overview, List<TourApiInfoItem> infoItems) {
        StringBuilder sb = new StringBuilder();
        if (overview != null) {
            sb.append(overview);
        }
        if (infoItems != null && !infoItems.isEmpty()) {
            for (TourApiInfoItem info : infoItems) {
                if (info.infoText() != null && !info.infoText().isBlank()) {
                    sb.append("\n");
                    if (info.infoName() != null && !info.infoName().isBlank()) {
                        sb.append(info.infoName()).append(": ");
                    }
                    sb.append(info.infoText().trim());
                }
            }
        }
        String result = sb.toString().trim();
        return result.isEmpty() ? null : result;
    }

    private String extractCity(String addr1) {
        if (addr1 == null || addr1.isBlank()) return null;
        String[] tokens = addr1.trim().split("\\s+");
        if (tokens.length < 2) return null;
        String second = tokens[1];
        return second.replaceAll("(시|군|구)$", "");
    }

    // overview() 접근자를 위해 common.overview()로 통일. infoItems() 오타 수정(infoItemss→infoItems).
    private record Candidate(
            TourApiListItem item,
            TourApiCommonResult common,
            TourAreaCode area,
            TourContentType type,
            String description,
            List<TourApiInfoItem> infoItems) {}

    public record CollectResult(
            int searched,
            int inserted,
            int skippedNoOverview) {}
}