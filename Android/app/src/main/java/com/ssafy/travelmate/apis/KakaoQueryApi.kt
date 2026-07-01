package com.ssafy.travelmate.apis

import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceResponse
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Query

interface KakaoQueryApi {

    @GET("api/places/search")
    suspend fun searchPlaces(
        @Query("query") query: String
    ): Response<List<PlaceResponse>>
}
