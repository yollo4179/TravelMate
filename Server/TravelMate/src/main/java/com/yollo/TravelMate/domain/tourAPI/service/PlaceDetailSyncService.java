package com.yollo.TravelMate.domain.tourAPI.service;


import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.domain.tourAPI.client.TourApiDetailClient;
import com.yollo.TravelMate.domain.tourAPI.client.TourApiDetailClient.TourApiInfoItem;
import com.yollo.TravelMate.domain.tourAPI.client.TourApiDetailClient.TourApiIntroResult;
import com.yollo.TravelMate.domain.tourAPI.repository.PlaceDetailRepository;
import com.yollo.TravelMate.domain.tourAPI.repository.PlaceDetailRepository.ProgramInsert;


@Service
public class PlaceDetailSyncService {

    private static final Logger log = LoggerFactory.getLogger(PlaceDetailSyncService.class);

    private final TourApiDetailClient client;
    private final PlaceDetailRepository repository;

    public PlaceDetailSyncService(TourApiDetailClient client, PlaceDetailRepository repository) {
        this.client = client;
        this.repository = repository;
    }

    /**
     * 특정 place에 대해 TourAPI 상세정보(detailIntro1/detailInfo1)를 가져와 저장합니다.
     * contentId/contentTypeId가 없으면(Kakao 출처 등) 호출하지 않아야 합니다 — 호출부에서 tour_content_id null 체크 필요.
     */
    public void syncDetail(Long placeId, String contentId, String contentTypeId) {
        TourApiIntroResult intro = client.fetchIntro(contentId, contentTypeId);
        if (intro.rawIntroJson() != null) {
            repository.upsertIntro(placeId, intro.rawIntroJson());
        } else {
            log.warn("detailIntro1 결과 없어 place_details 저장 생략: placeId={}, contentId={}", placeId, contentId);
        }

        List<TourApiInfoItem> infoItems = client.fetchInfoItems(contentId, contentTypeId);
        List<ProgramInsert> toSave = infoItems.stream()
                .map(i -> new ProgramInsert(i.infoName(), i.infoText(), i.serialNum()))
                .toList();
        repository.replaceProgramItems(placeId, toSave);

        if (toSave.isEmpty()) {
            log.info("detailInfo1 결과 없음(체험 프로그램 없는 장소로 추정): placeId={}, contentId={}", placeId, contentId);
        }
    }
}