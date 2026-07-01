package com.ssafy.travelmate.data.remote.dto.responses.place

data class PlaceResponse(
    val placeName: String,
    val latitude: Double,
    val longitude: Double,
    val roadAddress: String,
    val categoryName: String,
    val kakaoPlaceId: String
)
