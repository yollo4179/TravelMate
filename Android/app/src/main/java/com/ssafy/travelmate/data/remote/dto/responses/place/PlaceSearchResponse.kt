package com.ssafy.travelmate.data.remote.dto.responses.place

data class PlaceSearchResponse(
    val placeId: Long,
    val name: String,
    val description: String?,
    val region: String?,
    val city: String?,
    val category: String?,
    val latitude: Double,
    val longitude: Double,
    val semanticScore: Double,
    val rerankScore: Float,
    val tourContentId: String?,
    val imageUrl: String?,
    val homepageUrl: String?
)
