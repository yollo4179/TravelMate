package com.ssafy.travelmate.repositories

import com.ssafy.travelmate.data.RetrofitUtil
import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceSearchResponse

class PlaceSearchRepository {

    suspend fun searchPlaces(query: String): Result<List<PlaceSearchResponse>> {
        return try {
            val response = RetrofitUtil.placeSearchApi.searchPlaces(query)
            if (response.isSuccessful && response.body() != null) {
                Result.success(response.body()!!)
            } else {
                Result.failure(Exception("장소 검색 실패: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
