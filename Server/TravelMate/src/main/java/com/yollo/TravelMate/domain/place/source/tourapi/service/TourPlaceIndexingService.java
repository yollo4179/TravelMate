package com.yollo.TravelMate.domain.place.source.tourapi.service;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.data.internal.PlaceCreateCommand;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourCoordinateStatus;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourPlaceProcessingReason;
import com.yollo.TravelMate.domain.place.source.tourapi.data.TourPlaceCandidate;
import com.yollo.TravelMate.domain.place.source.tourapi.data.TourPlaceProcessingRecord;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceCoordinateValidator;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceRawMapper;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository.RawRow;

import lombok.Builder;
import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class TourPlaceIndexingService {

    private static final Logger log = LoggerFactory.getLogger(TourPlaceIndexingService.class);
    private static final int BATCH_SIZE = 64;

    private final TourPlaceRawRepository rawRepository;
    private final TourPlaceRawMapper rawMapper;
    private final TourPlaceCoordinateValidator coordinateValidator;
    private final EmbeddingClient embeddingClient;
    private final TourPlacePersistenceService persistenceService;

    public ProcessResult processRaw(int limit) {
        List<RawRow> rawRows = rawRepository.findUnprocessed(limit);
        if (rawRows.isEmpty()) {
            return ProcessResult.builder().processingRecords(List.of()).build();
        }

        List<TourPlaceCandidate> candidates = new ArrayList<>(rawRows.size());
        List<TourPlaceProcessingRecord> processingRecords = new ArrayList<>(rawRows.size());
        int skippedWithoutOverview = 0;
        int skippedUnparseable = 0;
        int skippedInvalidCoordinates = 0;

        int pageLimit = limit;
        while (!rawRows.isEmpty()) {
            for (RawRow rawRow : rawRows) {
                Optional<TourPlaceCandidate> candidate = rawMapper.map(rawRow);
                if (candidate.isEmpty()) {
                    skippedUnparseable++;
                    processingRecords.add(TourPlaceProcessingRecord.from(
                            rawRow,
                            null,
                            null,
                            TourPlaceProcessingReason.PARSE_FAILED
                    ));
                    continue;
                }
                TourPlaceCandidate mappedCandidate = candidate.get();
                TourCoordinateStatus coordinateStatus = coordinateValidator.validate(
                        mappedCandidate.item().mapY(),
                        mappedCandidate.item().mapX()
                );
                if (coordinateStatus != TourCoordinateStatus.VALID) {
                    skippedInvalidCoordinates++;
                    processingRecords.add(TourPlaceProcessingRecord.from(
                            rawRow,
                            mappedCandidate,
                            coordinateStatus,
                            TourPlaceProcessingReason.INVALID_COORDINATES
                    ));
                    log.warn("좌표 검증 실패로 원본을 미처리 상태로 보존합니다: tourContentId={}, status={}",
                            rawRow.tourContentId(), coordinateStatus);
                    continue;
                }
                if (!mappedCandidate.hasSearchableContent()) {
                    skippedWithoutOverview++;
                }
                processingRecords.add(TourPlaceProcessingRecord.from(
                        rawRow,
                        mappedCandidate,
                        coordinateStatus,
                        mappedCandidate.hasSearchableContent()
                                ? TourPlaceProcessingReason.INDEXED
                                : TourPlaceProcessingReason.INDEXED_WITHOUT_SEARCHABLE_CONTENT
                ));
                candidates.add(mappedCandidate);
            }
            if (candidates.size() == limit || rawRows.size() < pageLimit) {
                break;
            }
            // 저장으로 미처리 목록이 바뀌기 전에 오류 행 뒤까지 조회해야 offset이 유지된다.
            pageLimit = limit - candidates.size();
            rawRows = rawRepository.findUnprocessed(pageLimit, processingRecords.size());
        }

        for (int startIndex = 0; startIndex < candidates.size(); startIndex += BATCH_SIZE) {
            int endIndex = Math.min(startIndex + BATCH_SIZE, candidates.size());
            indexBatch(List.copyOf(candidates.subList(startIndex, endIndex)));
        }

        return ProcessResult.builder()
                .read(processingRecords.size())
                .indexed(candidates.size())
                .skippedWithoutOverview(skippedWithoutOverview)
                .skippedUnparseable(skippedUnparseable)
                .skippedInvalidCoordinates(skippedInvalidCoordinates)
                .processingRecords(processingRecords)
                .build();
    }

    private void indexBatch(List<TourPlaceCandidate> candidates) {
        List<Integer> embeddingTargetIndexes = new ArrayList<>();
        List<String> embeddingTexts = new ArrayList<>();

        for (int index = 0; index < candidates.size(); index++) {
            TourPlaceCandidate candidate = candidates.get(index);
            if (!candidate.hasSearchableContent()) {
                continue;
            }
            embeddingTargetIndexes.add(index);
            embeddingTexts.add(candidate.item().title() + ". " + candidate.description());
        }

        List<float[]> embeddings = embed(embeddingTexts);
        float[][] embeddingsByCandidate = new float[candidates.size()][];
        for (int index = 0; index < embeddingTargetIndexes.size(); index++) {
            embeddingsByCandidate[embeddingTargetIndexes.get(index)] = embeddings.get(index);
        }

        List<PlaceCreateCommand> createCommands = new ArrayList<>(candidates.size());
        for (int index = 0; index < candidates.size(); index++) {
            createCommands.add(toCreateCommand(
                    candidates.get(index),
                    embeddingsByCandidate[index]
            ));
        }

        persistenceService.saveBatch(candidates, createCommands);
        log.info("TourAPI 장소 인덱싱 완료: {}건", candidates.size());
    }

    private List<float[]> embed(List<String> embeddingTexts) {
        if (embeddingTexts.isEmpty()) {
            return List.of();
        }

        List<float[]> embeddings;
        try {
            embeddings = embeddingClient.embedBatch(embeddingTexts);
        } catch (Exception exception) {
            throw new IllegalStateException("임베딩 서버 호출 실패로 TourAPI 인덱싱을 중단합니다.", exception);
        }

        if (embeddings.size() != embeddingTexts.size()) {
            throw new IllegalStateException(
                    "임베딩 결과 수가 요청 수와 일치하지 않습니다. requested="
                            + embeddingTexts.size()
                            + ", returned="
                            + embeddings.size()
            );
        }
        return embeddings;
    }

    private PlaceCreateCommand toCreateCommand(
            TourPlaceCandidate candidate,
            float[] embedding
    ) {
        return new PlaceCreateCommand(
                candidate.item().title(),
                candidate.description(),
                candidate.region(),
                candidate.city(),
                candidate.contentType().getLabel(),
                candidate.sourceCategory() == null ? "tourapi" : candidate.sourceCategory(),
                candidate.item().mapY(),
                candidate.item().mapX(),
                candidate.item().contentId(),
                candidate.item().contentTypeId(),
                candidate.item().imageUrl(),
                candidate.common().homepageUrl(),
                embedding
        );
    }

    @Builder
    public record ProcessResult(
            int read,
            int indexed,
            int skippedWithoutOverview,
            int skippedUnparseable,
            int skippedInvalidCoordinates,
            List<TourPlaceProcessingRecord> processingRecords
    ) {
        public ProcessResult {
            processingRecords = List.copyOf(processingRecords);
        }
    }
}
