package com.yollo.TravelMate.domain.place.source.tourapi;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.data.internal.PlaceCreateCommand;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiCommonResult;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiInfoItem;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.place.source.tourapi.data.TourPlaceCandidate;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceCoordinateValidator;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceDescriptionBuilder;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceRawMapper;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository.RawRow;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceIndexingService;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlacePersistenceService;

class TourPlaceIndexingQualityTest {

    private final TourPlaceRawRepository rawRepository = mock(TourPlaceRawRepository.class);
    private final TourPlaceRawMapper rawMapper = mock(TourPlaceRawMapper.class);
    private final EmbeddingClient embeddingClient = mock(EmbeddingClient.class);
    private final TourPlacePersistenceService persistenceService = mock(TourPlacePersistenceService.class);
    private final TourPlaceIndexingService indexingService = new TourPlaceIndexingService(
            rawRepository,
            rawMapper,
            new TourPlaceCoordinateValidator(),
            embeddingClient,
            persistenceService
    );

    private TourPlaceCandidate stagedCandidate(
            String overview,
            List<TourApiInfoItem> information,
            double latitude,
            double longitude
    ) throws Exception {
        var source = new ObjectMapper().createObjectNode();
        source.put("contentid", "example");
        source.put("contenttypeid", "12");
        source.put("title", "검증 공원");
        source.put("mapy", latitude);
        source.put("mapx", longitude);
        var item = TourApiPlaceListClient.toListItem(source);
        var candidate = new TourPlaceCandidate(
                item,
                new TourApiCommonResult(overview, null, null, null),
                "서울",
                "중",
                TourContentType.관광지,
                "근린공원",
                new TourPlaceDescriptionBuilder().build(TourContentType.관광지, "근린공원", overview, information),
                information
        );
        var rawRow = new RawRow(item.contentId(), "12", source.toString(), null, null);
        when(rawRepository.findUnprocessed(100)).thenReturn(List.of(rawRow));
        when(rawMapper.map(rawRow)).thenReturn(java.util.Optional.of(candidate));
        return candidate;
    }

    @Test
    void supplementalInformationGetsAnEmbeddingWithoutAnOverview() throws Exception {
        var candidate = stagedCandidate(null, List.of(new TourApiInfoItem("이용가능시설", "팔각정", "0")), 37.57, 126.98);
        when(embeddingClient.embedBatch(anyList())).thenReturn(List.of(new float[]{0.1f, 0.2f}));
        var result = indexingService.processRaw(100);
        ArgumentCaptor<List<PlaceCreateCommand>> commands = ArgumentCaptor.forClass(List.class);
        verify(persistenceService).saveBatch(org.mockito.ArgumentMatchers.eq(List.of(candidate)), commands.capture());
        verify(embeddingClient).embedBatch(List.of("검증 공원. " + candidate.description()));
        assertNotNull(commands.getValue().get(0).embedding());
        assertEquals(0, result.skippedWithoutOverview());
    }

    @Test
    void categoryOnlyRecordsAreNotEmbedded() throws Exception {
        var candidate = stagedCandidate(null, List.of(), 37.57, 126.98);
        var result = indexingService.processRaw(100);
        verifyNoInteractions(embeddingClient);
        ArgumentCaptor<List<PlaceCreateCommand>> commands = ArgumentCaptor.forClass(List.class);
        verify(persistenceService).saveBatch(org.mockito.ArgumentMatchers.eq(List.of(candidate)), commands.capture());
        assertNull(commands.getValue().get(0).embedding());
        assertEquals(1, result.skippedWithoutOverview());
    }

    @Test
    void invalidCoordinatesCannotReachEmbeddingOrPersistence() throws Exception {
        stagedCandidate("산책 가능한 공원", List.of(), 19.69442748, 117.9925662504);
        var result = indexingService.processRaw(100);
        verifyNoInteractions(embeddingClient, persistenceService);
        assertEquals(1, result.skippedInvalidCoordinates());
        assertEquals(0, result.indexed());
    }

    @Test
    void embeddingCountMismatchDoesNotSaveAnyCandidates() throws Exception {
        stagedCandidate("산책 가능한 공원", List.of(), 37.57, 126.98);
        when(embeddingClient.embedBatch(anyList())).thenReturn(List.of());
        assertThrows(IllegalStateException.class, () -> indexingService.processRaw(100));
        verifyNoInteractions(persistenceService);
    }

    @Test
    void emptyRawQueueHasNoExternalEffects() {
        when(rawRepository.findUnprocessed(100)).thenReturn(List.of());
        assertEquals(0, indexingService.processRaw(100).read());
        verifyNoInteractions(rawMapper, embeddingClient, persistenceService);
    }
}
