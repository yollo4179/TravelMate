package com.ssafy.travelmate.util.states

import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceSearchResponse

enum class SearchStatus { IDLE, LOADING, SUCCESS, EMPTY, ERROR }
enum class MapStatus { LOADING, READY, ERROR }

data class SearchContext(
    val query: String = "",
    val region: String? = null,
    val city: String? = null,
    val category: String? = null,
    val limit: Int = 10,
    val planContext: com.ssafy.travelmate.data.remote.dto.requests.plan.PlanContext? = null
)

data class SearchState(
    val context: SearchContext = SearchContext(),
    val status: SearchStatus = SearchStatus.IDLE,
    val places: List<PlaceSearchResponse> = emptyList(),
    val errorMessage: String? = null
)

data class MapState(
    val status: MapStatus = MapStatus.LOADING,
    val selectedPlaceId: Long? = null,
    val personalPins: List<Pair<Double, Double>> = emptyList()
)
