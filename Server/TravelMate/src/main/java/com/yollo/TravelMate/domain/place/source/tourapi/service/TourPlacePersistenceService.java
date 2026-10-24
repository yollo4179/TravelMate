package com.yollo.TravelMate.domain.place.source.tourapi.service;

import java.util.List;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.yollo.TravelMate.domain.place.data.internal.PlaceCreateCommand;
import com.yollo.TravelMate.domain.place.repository.PlaceCatalogRepository;
import com.yollo.TravelMate.domain.place.repository.PlaceDetailRepository;
import com.yollo.TravelMate.domain.place.repository.PlaceDetailRepository.ProgramInsert;
import com.yollo.TravelMate.domain.place.source.tourapi.data.TourPlaceCandidate;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class TourPlacePersistenceService {

    private final PlaceCatalogRepository placeCatalogRepository;
    private final PlaceDetailRepository placeDetailRepository;
    private final TourPlaceRawRepository rawRepository;

    @Transactional
    public void saveBatch(
            List<TourPlaceCandidate> candidates,
            List<PlaceCreateCommand> createCommands
    ) {
        placeCatalogRepository.insertBatch(createCommands);
        candidates.forEach(this::savePrograms);
        candidates.stream()
                .map(candidate -> candidate.item().contentId())
                .forEach(rawRepository::markProcessed);
    }

    private void savePrograms(TourPlaceCandidate candidate) {
        if (candidate.informationItems().isEmpty()) {
            return;
        }

        Long placeId = placeCatalogRepository.findIdByTourContentId(candidate.item().contentId());
        if (placeId == null) {
            return;
        }

        List<ProgramInsert> programs = candidate.informationItems().stream()
                .map(item -> new ProgramInsert(
                        item.infoName(),
                        item.infoText(),
                        item.serialNum()
                ))
                .toList();
        placeDetailRepository.replaceProgramItems(placeId, programs);
    }
}
