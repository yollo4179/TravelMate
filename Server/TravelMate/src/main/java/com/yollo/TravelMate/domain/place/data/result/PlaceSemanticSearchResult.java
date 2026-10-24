package com.yollo.TravelMate.domain.place.data.result;

/** 재랭킹까지 거친 의미검색 결과 한 건. rerankScore를 버리지 않고 같이 들고 다닌다(로깅/디버깅/향후 LLM 프롬프트 근거용). */
public record PlaceSemanticSearchResult(
        PlaceResult place,
        float rerankScore
) {}
