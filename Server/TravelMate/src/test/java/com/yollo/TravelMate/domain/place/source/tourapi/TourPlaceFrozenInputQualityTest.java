package com.yollo.TravelMate.domain.place.source.tourapi;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import java.util.stream.StreamSupport;
import java.util.stream.Stream;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.source.tourapi.classification.LclsSystemCodeLookup;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourCoordinateStatus;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourPlaceProcessingReason;
import com.yollo.TravelMate.domain.place.source.tourapi.data.TourPlaceCandidate;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceCoordinateValidator;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceDescriptionBuilder;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceRawMapper;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository.RawRow;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceIndexingService;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlacePersistenceService;
import com.yollo.TravelMate.domain.place.source.tourapi.support.TourPlaceTextNormalizer;

class TourPlaceFrozenInputQualityTest {

    private final ObjectMapper json = new ObjectMapper();
    private final TourPlaceRawMapper mapper = new TourPlaceRawMapper(
            json,
            new LclsSystemCodeLookup(json),
            new TourPlaceDescriptionBuilder()
    );
    private final TourPlaceCoordinateValidator coordinates = new TourPlaceCoordinateValidator();
    private final TourPlaceRawRepository repository = mock(TourPlaceRawRepository.class);
    private final EmbeddingClient embeddings = mock(EmbeddingClient.class);
    private final TourPlacePersistenceService persistence = mock(TourPlacePersistenceService.class);
    private final TourPlaceIndexingService indexing = new TourPlaceIndexingService(
            repository,
            mapper,
            coordinates,
            embeddings,
            persistence
    );

    @Test
    @SuppressWarnings("unchecked")
    void frozenRowsKeepOriginalValuesSeparateFromNormalizedValuesAndReasons() throws Exception {
        Path snapshot = Path.of("../../Evaluation/datasets/v1.4.0/source/snapshot.json");
        byte[] originalBytes = Files.readAllBytes(snapshot);
        List<RawRow> rows = StreamSupport.stream(json.readTree(originalBytes).path("tour_api_raw").spliterator(), false)
                .map(this::rawRow)
                .toList();
        assertFalse(rows.isEmpty());
        Map<String, RawRow> originals = rows.stream().collect(Collectors.toMap(RawRow::tourContentId, Function.identity()));
        when(repository.findUnprocessed(rows.size())).thenReturn(rows);
        when(embeddings.embedBatch(anyList())).thenAnswer(invocation -> {
            List<String> texts = invocation.getArgument(0);
            return texts.stream().map(text -> new float[]{0.1f, 0.2f}).toList();
        });

        var result = indexing.processRaw(rows.size());
        assertEquals(rows.size(), result.read());
        assertEquals(rows.size(), result.processingRecords().size());
        assertEquals(0, result.skippedUnparseable());
        assertTrue(result.skippedInvalidCoordinates() > 0);
        assertEquals(result.read(), result.indexed() + result.skippedInvalidCoordinates());
        result.processingRecords().forEach(record -> {
            RawRow original = originals.get(record.tourContentId());
            TourPlaceCandidate candidate = mapper.map(original).orElseThrow();
            assertEquals(original.rawList(), record.originalListJson());
            assertEquals(original.rawCommon(), record.originalCommonJson());
            assertEquals(original.rawInfo(), record.originalInfoJson());
            assertEquals(candidate.description(), record.normalizedDescription());
            assertEquals(candidate.item().mapY(), record.normalizedLatitude());
            assertEquals(candidate.item().mapX(), record.normalizedLongitude());
            assertEquals(coordinates.validate(candidate.item().mapY(), candidate.item().mapX()), record.coordinateStatus());
            if (record.coordinateStatus() != TourCoordinateStatus.VALID) {
                assertEquals(TourPlaceProcessingReason.INVALID_COORDINATES, record.reason());
                return;
            }
            assertEquals(candidate.hasSearchableContent()
                    ? TourPlaceProcessingReason.INDEXED
                    : TourPlaceProcessingReason.INDEXED_WITHOUT_SEARCHABLE_CONTENT, record.reason());
            candidate.informationItems().stream().filter(item -> item.hasContent()).forEach(item -> assertTrue(
                    record.normalizedDescription().contains(TourPlaceTextNormalizer.normalizeHeading(item.infoName())
                            + ": " + TourPlaceTextNormalizer.normalize(item.infoText())),
                    original.tourContentId()
            ));
        });
        assertTrue(rows.stream().map(mapper::map).map(candidate -> candidate.orElseThrow()).anyMatch(candidate ->
                TourPlaceTextNormalizer.normalize(candidate.common().overview()).isBlank() && candidate.hasSearchableContent()
        ));
        ArgumentCaptor<List<TourPlaceCandidate>> saved = ArgumentCaptor.forClass(List.class);
        verify(persistence, atLeastOnce()).saveBatch(saved.capture(), anyList());
        List<TourPlaceCandidate> savedCandidates = saved.getAllValues().stream().flatMap(List::stream).toList();
        assertEquals(result.indexed(), savedCandidates.size());
        assertTrue(savedCandidates.stream().allMatch(candidate ->
                coordinates.validate(candidate.item().mapY(), candidate.item().mapX()) == TourCoordinateStatus.VALID
        ));
        verify(repository).findUnprocessed(rows.size());
        verifyNoMoreInteractions(repository);
        assertArrayEquals(originalBytes, Files.readAllBytes(snapshot));
    }

    private RawRow rawRow(JsonNode row) {
        return new RawRow(
                row.path("tour_content_id").asText(),
                row.path("tour_content_type_id").asText(),
                originalJson(row.path("raw_list")),
                originalJson(row.path("raw_common")),
                originalJson(row.path("raw_info"))
        );
    }

    private String originalJson(JsonNode node) {
        return node.isNull() || node.isMissingNode() ? null : node.toString();
    }

    @ParameterizedTest
    @ValueSource(strings = {"not-json", "null", "[]", "{}", "{\"contentid\":\"broken\",\"mapx\":\"not-a-coordinate\"}"})
    void malformedListRowsRemainUnprocessedWithOriginalEvidence(String originalList) {
        assertRejected(new RawRow("broken", "12", originalList, null, null));
    }

    @ParameterizedTest
    @ValueSource(strings = {"not-json", "null", "[]", "{}"})
    void malformedCommonRowsCannotBecomeLegitimateMissingContent(String originalCommon) {
        assertRejected(new RawRow("broken", "12", validList(), originalCommon, null));
    }

    @ParameterizedTest
    @ValueSource(strings = {"not-json", "null", "\"\"", "{}", "[null]", "[{}]", "[1]"})
    void malformedSupplementalRowsCannotBecomeEmptyProgramLists(String originalInfo) {
        assertRejected(new RawRow("broken", "12", validList(), null, originalInfo));
    }

    private String validList() {
        return "{\"contentid\":\"broken\",\"mapx\":\"127\",\"mapy\":\"37\"}";
    }

    static Stream<Arguments> invalidCoordinates() {
        return Stream.of(
                Arguments.of("null", "127", TourCoordinateStatus.MISSING),
                Arguments.of("\"\"", "127", TourCoordinateStatus.MISSING),
                Arguments.of("37", "null", TourCoordinateStatus.MISSING),
                Arguments.of("\"NaN\"", "127", TourCoordinateStatus.NON_FINITE),
                Arguments.of("37", "\"Infinity\"", TourCoordinateStatus.NON_FINITE),
                Arguments.of("\"-Infinity\"", "127", TourCoordinateStatus.NON_FINITE),
                Arguments.of("0", "0", TourCoordinateStatus.OUTSIDE_DOMESTIC_RANGE),
                Arguments.of("127", "37", TourCoordinateStatus.OUTSIDE_DOMESTIC_RANGE)
        );
    }

    @ParameterizedTest
    @MethodSource("invalidCoordinates")
    void invalidCoordinatesRetainTheirOriginalValuesAndNeverReachPersistence(
            String latitude,
            String longitude,
            TourCoordinateStatus expectedStatus
    ) {
        String originalList = "{\"contentid\":\"broken\",\"mapy\":" + latitude + ",\"mapx\":" + longitude + "}";
        RawRow original = new RawRow("broken", "12", originalList, null, null);
        when(repository.findUnprocessed(1)).thenReturn(List.of(original));
        var result = indexing.processRaw(1);
        assertEquals(0, result.indexed());
        assertEquals(1, result.skippedInvalidCoordinates());
        var record = result.processingRecords().get(0);
        assertEquals(expectedStatus, record.coordinateStatus());
        assertEquals(TourPlaceProcessingReason.INVALID_COORDINATES, record.reason());
        assertEquals(originalList, record.originalListJson());
        verify(repository).findUnprocessed(1);
        verifyNoMoreInteractions(repository);
        verifyNoInteractions(embeddings, persistence);
    }

    private void assertRejected(RawRow original) {
        when(repository.findUnprocessed(1)).thenReturn(List.of(original));
        var result = indexing.processRaw(1);
        assertEquals(1, result.skippedUnparseable());
        assertEquals(0, result.indexed());
        var record = result.processingRecords().get(0);
        assertEquals(TourPlaceProcessingReason.PARSE_FAILED, record.reason());
        assertEquals(original.rawList(), record.originalListJson());
        assertEquals(original.rawCommon(), record.originalCommonJson());
        assertEquals(original.rawInfo(), record.originalInfoJson());
        assertNull(record.normalizedDescription());
        verify(repository).findUnprocessed(1);
        verifyNoMoreInteractions(repository);
        verifyNoInteractions(embeddings, persistence);
    }
}
