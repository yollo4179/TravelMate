package com.yollo.TravelMate.domain.place.controller;

import java.util.List;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.yollo.TravelMate.domain.place.service.ReembeddingService;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourAreaCode;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourSigunguCode;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceIndexingService;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceRawCollectionService;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import lombok.RequiredArgsConstructor;

@RestController
@RequiredArgsConstructor
public class PlaceAdminController {

    private final ReembeddingService reembedding;
    private final TourPlaceRawCollectionService tourRawCollector;
    private final TourPlaceIndexingService tourPlaceIndexingService;

    @PostMapping("/admin/places/reembed")
    public String reembedAll() {
        int n = reembedding.reembedAll();
        return "재임베딩 완료: " + n + "건";
    }
    @Operation(summary = "TourAPI 시군구 단위 세부지역 raw 수집 (1단계)", description = "지정한 시군구들만 콕 집어서 TourAPI 원본 JSON을 "
            + "tour_api_raw에 저장합니다. 임베딩/places 적재는 하지 않습니다 (2단계 processRaw가 담당). "
            + "지역(시도) 전체가 아니라 구/시/군 단위로 좁혀서 쿼터를 아끼고 싶을 때 사용합니다.")
    @PostMapping("/admin/places/collect/tour/sigungu")
    public TourPlaceRawCollectionService.CollectRawResult collectTourBySigungu(
            @Parameter(
                    description = "수집할 시군구 목록. TourSigunguCode enum 상수명(지역명_시군구명)을 그대로 씁니다. "
                            + "예: 서울_강남구, 인천_강화군. 같은 지역 안에서도 시군구코드가 다르면 다른 값이니 정확한 상수명을 넣어야 합니다.",
                    example = "서울_강남구",
                    required = true)
            @RequestParam List<TourSigunguCode> sigungu,

            @Parameter(
                    description = "필터링할 콘텐츠 타입(관광지/문화시설/축제공연행사/여행코스/레포츠/숙박/쇼핑/음식점). "
                            + "생략하면 전체 타입을 다 수집합니다.",
                    example = "관광지",
                    required = false)
            @RequestParam(required = false) List<TourContentType> types) {
        return tourRawCollector.collectRaw(null, types, sigungu);
    }

    @Operation(summary = "TourAPI raw 수집 재개 (특정 페이지부터)", description = "이전 수집이 쿼터 소진 등으로 중간에 끊겼을 때, "
            + "1페이지부터 다시 훑지 않고 끊긴 지점(page)부터 바로 이어서 수집합니다. sigungu를 생략하면 지역 전체 기준 페이지입니다.")
    @PostMapping("/admin/places/collect/tour/resume")
    public TourPlaceRawCollectionService.CollectRawResult resumeTourCollect(
            @Parameter(description = "지역(시도). TourAreaCode enum 상수명.", example = "서울", required = true)
            @RequestParam TourAreaCode area,

            @Parameter(description = "시군구(선택). 지정하면 그 시군구 기준으로 페이지를 넘김.", example = "서울_강남구")
            @RequestParam(required = false) TourSigunguCode sigungu,

            @Parameter(description = "콘텐츠 타입.", example = "관광지", required = true)
            @RequestParam TourContentType type,

            @Parameter(description = "이어서 시작할 페이지 번호 (1부터, 지난 수집 로그의 마지막 페이지+1 등)", example = "9", required = true)
            @RequestParam int page,

            @Parameter(description = "한 페이지당 건수. 이전 수집 때와 동일한 값을 써야 페이지 경계가 어긋나지 않음.", example = "100")
            @RequestParam(defaultValue = "100") int numOfRows) {
        return tourRawCollector.collectRawFromPage(area, sigungu, type, page, numOfRows);
    }

    @Operation(summary = "TourAPI raw 가공 (2단계)", description = "tour_api_raw에 쌓인 미처리 원본 JSON을 읽어 "
            + "description 조립 + 임베딩 + places 적재를 합니다. TourAPI를 다시 호출하지 않으므로 "
            + "description 조립 로직을 바꾼 뒤 재실행해도 쿼터를 쓰지 않습니다.")
    @PostMapping("/admin/places/process/tour")
    public TourPlaceIndexingService.ProcessResult processTourRaw(
            @Parameter(description = "한 번에 처리할 최대 건수", example = "500")
            @RequestParam(defaultValue = "500") int limit) {
        return tourPlaceIndexingService.processRaw(limit);
    }
}
