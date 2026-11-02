package com.yollo.TravelMate.domain.place.source.tourapi;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.IntStream;
import java.util.stream.Stream;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.repository.PlaceCatalogRepository;
import com.yollo.TravelMate.domain.place.repository.PlaceDetailRepository;
import com.yollo.TravelMate.domain.place.source.tourapi.classification.LclsSystemCodeLookup;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourCoordinateStatus;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourPlaceProcessingReason;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository.RawRow;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceCoordinateValidator;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceDescriptionBuilder;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceRawMapper;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceIndexingService;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlacePersistenceService;

class TourPlaceIndexingProgressTest {

    private final ObjectMapper json = new ObjectMapper();
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final PlaceCatalogRepository catalog = mock(PlaceCatalogRepository.class);
    private final PlaceDetailRepository details = mock(PlaceDetailRepository.class);
    private final EmbeddingClient embeddings = mock(EmbeddingClient.class);
    private final TourPlaceRawRepository repository = new TourPlaceRawRepository(jdbc);
    private final TourPlaceIndexingService indexing = new TourPlaceIndexingService(
            repository,
            new TourPlaceRawMapper(json, new LclsSystemCodeLookup(json), new TourPlaceDescriptionBuilder()),
            new TourPlaceCoordinateValidator(),
            embeddings,
            new TourPlacePersistenceService(catalog, details, repository)
    );
    private final Set<String> processedIds = new HashSet<>();
    private final List<Integer> queriedOffsets = new ArrayList<>();

    @ParameterizedTest
    @CsvSource({"1, 1", "1, 3", "2, 3"})
    void olderCoordinateErrorsDoNotBlockLaterValidRowsAcrossRuns(
            int limit,
            int errorCount
    ) {
        List<RawRow> errors = rows("00-error-", errorCount, 0.0);
        List<RawRow> valid = rows("10-valid-", limit * 2, 37.57);
        List<RawRow> originals = Stream.concat(errors.stream(), valid.stream()).toList();
        simulateStoredRows(originals);
        when(embeddings.embedBatch(anyList())).thenAnswer(invocation -> {
            List<String> texts = invocation.getArgument(0);
            return texts.stream().map(text -> new float[]{0.1f, 0.2f}).toList();
        });

        for (int run = 0; run < 2; run++) {
            var result = indexing.processRaw(limit);
            assertEquals(limit, result.indexed());
            assertEquals(errorCount, result.skippedInvalidCoordinates());
            assertEquals(limit + errorCount, result.read());
            assertEquals(0, result.skippedUnparseable());
            List<String> expectedIds = valid.subList(run * limit, (run + 1) * limit).stream()
                    .map(RawRow::tourContentId)
                    .toList();
            assertEquals(expectedIds, result.processingRecords().stream()
                    .filter(record -> record.reason() == TourPlaceProcessingReason.INDEXED)
                    .map(record -> record.tourContentId())
                    .toList());
            assertEquals(errors.stream().map(RawRow::rawList).toList(), result.processingRecords().stream()
                    .filter(record -> record.reason() == TourPlaceProcessingReason.INVALID_COORDINATES)
                    .peek(record -> assertEquals(TourCoordinateStatus.OUTSIDE_DOMESTIC_RANGE, record.coordinateStatus()))
                    .map(record -> record.originalListJson())
                    .toList());
            assertTrue(errors.stream().noneMatch(row -> processedIds.contains(row.tourContentId())));
            assertEquals((run + 1) * limit, processedIds.size());
        }

        var onlyErrorsRemain = indexing.processRaw(limit);
        assertEquals(errorCount, onlyErrorsRemain.read());
        assertEquals(errorCount, onlyErrorsRemain.skippedInvalidCoordinates());
        assertEquals(0, onlyErrorsRemain.indexed());
        assertTrue(onlyErrorsRemain.processingRecords().stream().allMatch(record ->
                record.reason() == TourPlaceProcessingReason.INVALID_COORDINATES
        ));
        assertEquals(new HashSet<>(valid.stream().map(RawRow::tourContentId).toList()), processedIds);
        assertTrue(queriedOffsets.stream().anyMatch(offset -> offset > 0));
        verify(catalog, times(2)).insertBatch(anyList());
        verify(embeddings, times(2)).embedBatch(anyList());
        verifyNoInteractions(details);
    }

    @SuppressWarnings("unchecked")
    private void simulateStoredRows(List<RawRow> originals) {
        when(jdbc.query(anyString(), any(RowMapper.class), anyInt(), anyInt())).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            assertTrue(sql.replaceAll("\\s+", " ").contains("order by fetched_at, tour_content_id limit ? offset ?"));
            int limit = invocation.getArgument(2);
            int offset = invocation.getArgument(3);
            queriedOffsets.add(offset);
            return originals.stream()
                    .filter(row -> !processedIds.contains(row.tourContentId()))
                    .skip(offset)
                    .limit(limit)
                    .toList();
        });
        when(jdbc.update(anyString(), anyString())).thenAnswer(invocation -> {
            assertEquals("update tour_api_raw set processed_at = now() where tour_content_id = ?", invocation.getArgument(0));
            assertTrue(processedIds.add(invocation.getArgument(1)));
            return 1;
        });
    }

    private List<RawRow> rows(
            String idPrefix,
            int count,
            double latitude
    ) {
        return IntStream.range(0, count).mapToObj(index -> {
            String contentId = idPrefix + index;
            String originalList = json.createObjectNode()
                    .put("contentid", contentId)
                    .put("contenttypeid", "12")
                    .put("title", "보존 장소 " + contentId)
                    .put("mapy", latitude)
                    .put("mapx", 126.98)
                    .toString();
            return new RawRow(contentId, "12", originalList, "{\"overview\":\"보존 본문\"}", null);
        }).toList();
    }
}
