package com.yollo.TravelMate.domain.place.source.tourapi.service;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.domain.place.repository.PlaceCatalogRepository;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiCommonResult;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient.TourApiInfoResult;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient.TourApiListItem;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient.TourApiListPage;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourAreaCode;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourSigunguCode;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository;

import lombok.RequiredArgsConstructor;

/**
 * 1단계: TourAPI를 호출해서 원본 JSON을 tour_api_raw에 그대로 저장만 한다.
 * description 조립, 임베딩, places 적재는 TourPlaceIndexingService가 담당합니다.
 * TourAPI가 일 1,000건 트래픽 제한이라 가공 로직을 바꿀 때마다 재수집하지 않기 위해 분리했다.
 */
@Service
@RequiredArgsConstructor
public class TourPlaceRawCollectionService {

    private static final Logger log = LoggerFactory.getLogger(TourPlaceRawCollectionService.class);

    private final TourApiPlaceListClient listClient;
    private final TourApiPlaceDetailClient detailClient;
    private final PlaceCatalogRepository placeCatalogRepository;
    private final TourPlaceRawRepository rawRepository;

    private static final int NUM_OF_ROWS = 100;

    public CollectRawResult collectRaw(List<TourAreaCode> areaFilter, List<TourContentType> typeFilter) {
        List<TourAreaCode> areas = (areaFilter != null) ? areaFilter : List.of(TourAreaCode.values());
        List<TourContentType> types = (typeFilter != null) ? typeFilter : List.of(TourContentType.values());

        RawCounts counts = new RawCounts();
        for (TourAreaCode area : areas) {
            for (TourContentType type : types) {
                collectRawOne(area, null, type, counts, 1, NUM_OF_ROWS);
            }
        }
        return new CollectRawResult(counts.searched, counts.saved, counts.skipped);
    }

    /**
     * 오버로드 - 시군구 단위 세부지역 수집.
     * sigunguFilter가 null이면 areaFilter 기준 지역 전체 수집으로 위임하고,
     * 값이 있으면 areaFilter는 무시하고 그 시군구들만 수집한다.
     */
    public CollectRawResult collectRaw(List<TourAreaCode> areaFilter, List<TourContentType> typeFilter,
                                        List<TourSigunguCode> sigunguFilter) {
        if (sigunguFilter == null) {
            return collectRaw(areaFilter, typeFilter);
        }

        List<TourContentType> types = (typeFilter != null) ? typeFilter : List.of(TourContentType.values());

        RawCounts counts = new RawCounts();
        for (TourSigunguCode sigungu : sigunguFilter) {
            for (TourContentType type : types) {
                collectRawOne(sigungu.getAreaCode(), sigungu, type, counts, 1, NUM_OF_ROWS);
            }
        }
        return new CollectRawResult(counts.searched, counts.saved, counts.skipped);
    }

    /**
     * 단일 지역(+시군구)·타입에 대해 특정 페이지부터 이어서 raw 수집.
     * 이전 수집이 쿼터 소진 등으로 중간에 끊겼을 때, 1페이지부터 다시 훑지 않고
     * 끊긴 지점(startPage)부터 바로 재개하기 위한 용도.
     * sigungu가 null이면 지역(시도) 전체 기준으로 페이지를 넘긴다.
     */
    public CollectRawResult collectRawFromPage(TourAreaCode area, TourSigunguCode sigungu, TourContentType type,
                                                int startPage, int numOfRows) {
        RawCounts counts = new RawCounts();
        collectRawOne(area, sigungu, type, counts, startPage, numOfRows);
        return new CollectRawResult(counts.searched, counts.saved, counts.skipped);
    }

    private void collectRawOne(TourAreaCode area, TourSigunguCode sigungu, TourContentType type, RawCounts counts,
                                int startPage, int numOfRows) {
        String label = (sigungu == null) ? area.getRegion() : area.getRegion() + " " + sigungu.getName();

        TourApiListPage startPageResult = (sigungu == null)
                ? listClient.fetchPage(area.getAreaCode(), type.getContentTypeId(), numOfRows, startPage)
                : listClient.fetchPage(area.getAreaCode(), sigungu.getSigunguCode(), type.getContentTypeId(), numOfRows, startPage);

        int totalCount = startPageResult.totalCount();
        if (totalCount == 0) {
            log.info("[{} - {}] 결과 없음 (startPage={})", label, type.getLabel(), startPage);
            return;
        }

        int totalPages = (int) Math.ceil((double) totalCount / numOfRows);
        if (startPage > totalPages) {
            log.info("[{} - {}] startPage({})가 totalPages({})보다 커서 수집할 게 없음", label, type.getLabel(), startPage, totalPages);
            return;
        }
        log.info("[{} - {}] 총 {}건, {}페이지 중 {}페이지부터 raw 수집 시작", label, type.getLabel(), totalCount, totalPages, startPage);

        for (int page = startPage; page <= totalPages; page++) {
            TourApiListPage listPage = (page == startPage)
                    ? startPageResult
                    : (sigungu == null)
                        ? listClient.fetchPage(area.getAreaCode(), type.getContentTypeId(), numOfRows, page)
                        : listClient.fetchPage(area.getAreaCode(), sigungu.getSigunguCode(), type.getContentTypeId(), numOfRows, page);

            for (TourApiListItem item : listPage.items()) {
                counts.searched++;
                if (item.contentId() == null) continue;

                // 이미 raw로 저장했거나 이미 처리까지 끝난 항목이면 TourAPI 재호출 안 함 (쿼터 절약)
                if (rawRepository.exists(item.contentId()) || placeCatalogRepository.existsByTourContentId(item.contentId())) {
                    counts.skipped++;
                    continue;
                }

                TourApiCommonResult common = detailClient.fetchCommon(item.contentId());
                TourApiInfoResult info = detailClient.fetchInfoItems(item.contentId(), item.contentTypeId());

                rawRepository.upsert(item.contentId(), item.contentTypeId(),
                        item.rawJson(), common.rawJson(), info.rawJson());
                counts.saved++;
            }
        }
    }

    private static final class RawCounts {
        int searched;
        int saved;
        int skipped;
    }

    public record CollectRawResult(int searched, int saved, int skipped) {}
}
