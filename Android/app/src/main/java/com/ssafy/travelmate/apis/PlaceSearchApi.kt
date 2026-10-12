package com.ssafy.travelmate.apis

import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceSearchResponse
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Query

interface PlaceSearchApi {

    @GET("api/places/search")
    suspend fun searchPlaces(
        @Query("query") query: String
    ): Response<List<PlaceSearchResponse>>
}
