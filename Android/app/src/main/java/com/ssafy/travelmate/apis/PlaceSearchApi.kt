package com.ssafy.travelmate.apis

import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceSearchResponse
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Query

interface PlaceSearchApi {

    @retrofit2.http.POST("api/v1/places/search")
    suspend fun searchWithinPlan(
        @retrofit2.http.Body request: com.ssafy.travelmate.data.remote.dto.requests.plan.ContextPlaceSearchRequest
    ): Response<List<PlaceSearchResponse>>

    @GET("api/places/search")
    suspend fun searchPlaces(
        @Query("query") query: String,
        @Query("region") region: String? = null,
        @Query("city") city: String? = null,
        @Query("category") category: String? = null,
        @Query("limit") limit: Int = 10
    ): Response<List<PlaceSearchResponse>>
}
