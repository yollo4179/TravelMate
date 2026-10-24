package com.ssafy.travelmate.viewmodels.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ssafy.travelmate.apis.PlanResponse
import com.ssafy.travelmate.data.remote.dto.requests.plan.*
import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceSearchResponse
import com.ssafy.travelmate.repositories.TravelPlanningRepository
import com.ssafy.travelmate.util.states.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.util.UUID
import javax.inject.Inject

@HiltViewModel
class TravelPlanningViewModel @Inject constructor(
    private val repository: TravelPlanningRepository
) : ViewModel() {
    private val mutableState = MutableStateFlow(TravelPlanningState())
    val state = mutableState.asStateFlow()
    private val mutablePlan = MutableStateFlow<PlanResponse?>(null)
    val plan = mutablePlan.asStateFlow()
    private var lastRequest: GeneratePlanRequest? = null
    private var lastMode: PlanningMode? = null
    private var requestKey = UUID.randomUUID().toString()

    fun chooseLocation(choice: LocationChoice) {
        mutableState.update { it.copy(locationChoice = choice, errorMessage = null) }
    }

    fun targetLocation(target: LocationTarget) {
        mutableState.update { it.copy(locationTarget = target, errorMessage = null) }
    }

    fun selectLocation(
        coordinate: Coordinate,
        label: String,
        source: LocationSource = LocationSource.SELECTED_POINT
    ) {
        val location = PlanLocation(coordinate, label, source)
        mutableState.update { previous ->
            when (previous.locationTarget) {
                LocationTarget.AREA -> previous.copy(
                    areaCenter = coordinate,
                    areaLabel = label,
                    origin = previous.origin ?: location,
                    locationChoice = if (source == LocationSource.GPS) LocationChoice.CURRENT else LocationChoice.SELECTED,
                    errorMessage = null
                )
                LocationTarget.ORIGIN -> previous.copy(origin = location, errorMessage = null)
                LocationTarget.DESTINATION -> previous.copy(destination = location, errorMessage = null)
            }
        }
    }

    fun clearDestination() { mutableState.update { it.copy(destination = null) } }
    fun changeRadius(radiusMeters: Int) {
        mutableState.update { it.copy(radiusMeters = radiusMeters.coerceIn(500, 10000)) }
    }
    fun updateConditions(conditions: TravelConditions) {
        mutableState.update { it.copy(conditions = conditions, errorMessage = null) }
    }
    fun showError(message: String) { mutableState.update { it.copy(errorMessage = message) } }

    fun chooseMode(mode: PlanningMode) {
        if (state.value.areaCenter == null || state.value.origin == null) {
            showError("현재 위치를 가져오거나 지도에서 여행할 위치를 길게 눌러 주세요.")
            return
        }
        mutableState.update { it.copy(mode = mode, step = PlanningStep.CONDITIONS, errorMessage = null) }
    }

    fun continueFromConditions() {
        try { state.value.request() } catch (exception: Exception) {
            showError(exception.message ?: "날짜와 여행 시간을 확인해 주세요.")
            return
        }
        if (state.value.mode == PlanningMode.AI) {
            submit()
            return
        }
        mutableState.update { it.copy(step = PlanningStep.PLACES, errorMessage = null) }
    }

    fun back() {
        if (state.value.status in setOf(PlanningStatus.SUBMITTING, PlanningStatus.RUNNING)) return
        mutableState.update {
            it.copy(
                step = when (it.step) {
                    PlanningStep.LOCATION, PlanningStep.CONDITIONS -> PlanningStep.LOCATION
                    PlanningStep.PLACES -> PlanningStep.CONDITIONS
                    PlanningStep.RESULT -> if (it.mode == PlanningMode.MANUAL) PlanningStep.PLACES else PlanningStep.CONDITIONS
                },
                status = PlanningStatus.IDLE,
                errorMessage = null
            )
        }
    }

    fun togglePlace(place: PlaceSearchResponse) {
        val previous = state.value
        if (previous.requiredStops.any { it.placeId == place.placeId }) {
            mutableState.update { it.copy(
                requiredStops = it.requiredStops.filterNot { stop -> stop.placeId == place.placeId },
                selectedPlaces = it.selectedPlaces.filterNot { selected -> selected.placeId == place.placeId }
            ) }
            return
        }
        if (previous.requiredStops.size >= 6) {
            showError("필수 방문 장소는 최대 6곳까지 담을 수 있습니다.")
            return
        }
        mutableState.update { it.copy(
            requiredStops = it.requiredStops + RequiredStop(place.placeId),
            selectedPlaces = it.selectedPlaces + place,
            errorMessage = null
        ) }
    }

    fun changeStay(placeId: Long, minutes: Int) {
        mutableState.update { it.copy(requiredStops = it.requiredStops.map { stop ->
            if (stop.placeId == placeId) stop.copy(stayMinutes = minutes.coerceIn(10, 360)) else stop
        }) }
    }

    fun submit() {
        if (state.value.status == PlanningStatus.SUBMITTING) return
        val request = try { state.value.request() } catch (exception: Exception) {
            showError(exception.message ?: "여행 조건을 확인해 주세요.")
            return
        }
        val mode = state.value.mode
        if (mode == PlanningMode.MANUAL && request.requiredStops.isEmpty()) {
            showError("방문할 장소를 하나 이상 담아 주세요.")
            return
        }
        if (lastRequest != request || lastMode != mode) {
            requestKey = UUID.randomUUID().toString()
            lastRequest = request
            lastMode = mode
        }
        mutableState.update { it.copy(status = PlanningStatus.SUBMITTING, errorMessage = null) }
        viewModelScope.launch {
            try {
                val result = repository.submit(request, mode, requestKey)
                mutablePlan.value = result
                mutableState.update { it.copy(step = PlanningStep.RESULT, status = PlanningStatus.SUCCESS, planId = result.planId) }
            } catch (timeout: kotlinx.coroutines.TimeoutCancellationException) {
                mutableState.update { it.copy(
                    status = PlanningStatus.ERROR,
                    errorMessage = "생성 결과를 기다리는 시간이 길어졌습니다. 다시 누르면 같은 요청의 진행 상태를 확인합니다."
                ) }
            } catch (cancelled: CancellationException) {
                mutableState.update { it.copy(status = PlanningStatus.IDLE) }
                throw cancelled
            } catch (exception: Exception) {
                val message = when (exception) {
                    is HttpException -> runCatching {
                        com.google.gson.JsonParser.parseString(exception.response()?.errorBody()?.string())
                            .asJsonObject.get("errorMessage").asString
                    }.getOrNull() ?: "여행 요청을 처리하지 못했습니다 (${exception.code()}). 조건을 확인하고 다시 시도해 주세요."
                    else -> exception.message ?: "서버에 연결하지 못했습니다. 다시 시도해 주세요."
                }
                mutableState.update { it.copy(status = PlanningStatus.ERROR, errorMessage = message) }
            }
        }
    }
}
