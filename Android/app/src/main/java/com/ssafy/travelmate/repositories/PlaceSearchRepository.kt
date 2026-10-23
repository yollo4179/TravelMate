package com.ssafy.travelmate.repositories

import com.ssafy.travelmate.apis.PlaceSearchApi
import com.ssafy.travelmate.util.states.SearchContext
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException
import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceSearchResponse

class PlaceSearchRepository(
    private val placeSearchApi: PlaceSearchApi
) {

    suspend fun searchPlaces(context: SearchContext): Result<List<PlaceSearchResponse>> {
        require(context.query.isNotBlank())
        require(context.limit in 1..20)
        return try {
            val response = if (context.planContext != null) {
                placeSearchApi.searchWithinPlan(
                    com.ssafy.travelmate.data.remote.dto.requests.plan.ContextPlaceSearchRequest(
                        context = context.planContext,
                        query = context.query,
                        limit = context.limit
                    )
                )
            } else placeSearchApi.searchPlaces(
                query = context.query,
                region = context.region,
                city = context.city,
                category = context.category,
                limit = context.limit
            )
            if (!response.isSuccessful) {
                return Result.failure(HttpException(response))
            }
            val places = response.body()
                ?: return Result.failure(IllegalStateException("검색 응답이 비어 있습니다."))
            Result.success(places)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
