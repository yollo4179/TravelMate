package com.ssafy.travelmate.repositories

import com.ssafy.travelmate.data.RetrofitUtil
import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceResponse

class KakaoQueryRepository {

    suspend fun searchPlaces(query: String): Result<List<PlaceResponse>> {
        return try {
            val response = RetrofitUtil.kakaoQueryApi.searchPlaces(query)
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
