package com.yollo.TravelMate.domain.place.controller;

import java.util.List;

import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import jakarta.validation.Valid;
import com.yollo.TravelMate.domain.place.data.request.PlaceSearchRequest;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.yollo.TravelMate.domain.place.data.response.PlaceSearchResponseDto;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;

@Validated
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/places")
public class PlaceSearchController {

    private final PlaceSemanticSearchService placeSemanticSearchService;

    @PostMapping("/search")
    public List<PlaceSearchResponseDto> search(@Valid @RequestBody PlaceSearchRequest request) {
        return placeSemanticSearchService.search(request).stream().map(PlaceSearchResponseDto::from).toList();
    }

    @GetMapping("/search")
    public List<PlaceSearchResponseDto> search(
            @NotBlank @RequestParam("query") String query,
            @RequestParam(name = "region", required = false) String region,
            @RequestParam(name = "city", required = false) String city,
            @RequestParam(name = "category", required = false) String category,
            @Min(1) @Max(20) @RequestParam(name = "limit", defaultValue = "10") int limit,
            @RequestParam(name = "rankingMode", defaultValue = "RERANKED") PlaceSemanticSearchService.RankingMode rankingMode
    ) {
        return placeSemanticSearchService.search(
                        query,
                        region,
                        city,
                        category,
                        limit,
                        null,
                        rankingMode
                ).stream()
                .map(PlaceSearchResponseDto::from)
                .toList();
    }
}
