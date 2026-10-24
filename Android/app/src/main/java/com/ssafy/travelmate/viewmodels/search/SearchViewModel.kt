package com.ssafy.travelmate.viewmodels.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ssafy.travelmate.repositories.PlaceSearchRepository
import com.ssafy.travelmate.util.states.MapState
import com.ssafy.travelmate.util.states.MapStatus
import com.ssafy.travelmate.util.states.SearchContext
import com.ssafy.travelmate.util.states.SearchState
import com.ssafy.travelmate.util.states.SearchStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class SearchViewModel @Inject constructor(
    private val placeSearchRepository: PlaceSearchRepository
) : ViewModel() {
    private val mutableSearchState = MutableStateFlow(SearchState())
    val searchState = mutableSearchState.asStateFlow()
    private val mutableMapState = MutableStateFlow(MapState())
    val mapState = mutableMapState.asStateFlow()
    private var searchJob: Job? = null
    private var searchVersion = 0L

    fun searchWithinPlan(context: com.ssafy.travelmate.data.remote.dto.requests.plan.PlanContext) {
        search(searchState.value.context.copy(planContext = context))
    }

    fun searchLocations() {
        search(searchState.value.context.copy(planContext = null))
    }

    fun updateQuery(query: String) {
        searchJob?.cancel()
        searchVersion++
        mutableMapState.update { it.copy(selectedPlaceId = null) }
        mutableSearchState.update { SearchState(context = it.context.copy(query = query)) }
    }

    fun search(context: SearchContext = searchState.value.context) {
        if (context.limit !in 1..20) return
        searchJob?.cancel()
        val version = ++searchVersion
        val normalizedContext = context.copy(query = context.query.trim())
        mutableMapState.update { it.copy(selectedPlaceId = null) }
        if (normalizedContext.query.isBlank()) {
            mutableSearchState.value = SearchState(context = normalizedContext)
            return
        }
        mutableSearchState.value = SearchState(
            context = normalizedContext,
            status = SearchStatus.LOADING
        )
        searchJob = viewModelScope.launch {
            val result = placeSearchRepository.searchPlaces(normalizedContext)
            // 이전 응답이 최신 검색의 핀과 목록을 덮어쓰지 않게 한다.
            if (version != searchVersion) return@launch
            result.fold(
                onSuccess = { places ->
                    mutableSearchState.update {
                        it.copy(
                            status = if (places.isEmpty()) SearchStatus.EMPTY else SearchStatus.SUCCESS,
                            places = places
                        )
                    }
                },
                onFailure = {
                    mutableSearchState.update {
                        it.copy(
                            status = SearchStatus.ERROR,
                            errorMessage = "장소 검색에 실패했습니다. 다시 시도해 주세요."
                        )
                    }
                }
            )
        }
    }

    fun selectPlace(placeId: Long) {
        if (searchState.value.places.none { it.placeId == placeId }) return
        mutableMapState.update { it.copy(selectedPlaceId = placeId) }
    }

    fun updateMapStatus(status: MapStatus) {
        mutableMapState.update { it.copy(status = status) }
    }

    fun addPersonalPin(latitude: Double, longitude: Double) {
        if (!latitude.isFinite() || !longitude.isFinite()) return
        if (latitude !in -90.0..90.0 || longitude !in -180.0..180.0) return
        mutableMapState.update {
            it.copy(personalPins = (it.personalPins + (latitude to longitude)).distinct())
        }
    }
}
