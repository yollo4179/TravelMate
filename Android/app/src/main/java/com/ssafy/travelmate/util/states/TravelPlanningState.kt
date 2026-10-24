package com.ssafy.travelmate.util.states

import com.ssafy.travelmate.data.remote.dto.requests.plan.*
import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceSearchResponse
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

enum class PlanningStep { LOCATION, CONDITIONS, PLACES, RESULT }
enum class PlanningMode { AI, MANUAL }
enum class LocationChoice { CURRENT, SELECTED }
enum class LocationTarget { AREA, ORIGIN, DESTINATION }
enum class PlanningStatus { IDLE, SUBMITTING, RUNNING, SUCCESS, ERROR }
enum class TravelTheme(val label: String) { WALK("산책"), CULTURE("문화"), CAFE("카페") }

data class TravelConditions(
    val date: String = SimpleDateFormat("yyyy-MM-dd", Locale.KOREA).apply {
        timeZone = TimeZone.getTimeZone("Asia/Seoul")
    }.format(Date()),
    val startTime: String = "10:00",
    val endTime: String = "17:00",
    val transportMode: TransportMode = TransportMode.WALK,
    val objective: PlanObjective = PlanObjective.DISTANCE,
    val themes: Set<TravelTheme> = emptySet(),
    val additionalRequest: String = "",
    val requireCafe: Boolean = false,
    val unknownHoursPolicy: UnknownHoursPolicy = UnknownHoursPolicy.EXCLUDE
)

data class TravelPlanningState(
    val step: PlanningStep = PlanningStep.LOCATION,
    val mode: PlanningMode = PlanningMode.MANUAL,
    val locationChoice: LocationChoice = LocationChoice.SELECTED,
    val locationTarget: LocationTarget = LocationTarget.AREA,
    val areaCenter: Coordinate? = null,
    val areaLabel: String = "위치를 선택해 주세요",
    val radiusMeters: Int = 3000,
    val origin: PlanLocation? = null,
    val destination: PlanLocation? = null,
    val conditions: TravelConditions = TravelConditions(),
    val requiredStops: List<RequiredStop> = emptyList(),
    val selectedPlaces: List<PlaceSearchResponse> = emptyList(),
    val status: PlanningStatus = PlanningStatus.IDLE,
    val errorMessage: String? = null,
    val planId: Long? = null
) {
    fun request(): GeneratePlanRequest {
        val center = requireNotNull(areaCenter) { "여행할 위치를 선택해 주세요." }
        val departure = requireNotNull(origin) { "출발 지점을 선택해 주세요." }
        val dateFormat = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.KOREA).apply {
            isLenient = false
            timeZone = TimeZone.getTimeZone("Asia/Seoul")
        }
        val start = requireNotNull(dateFormat.parse("${conditions.date} ${conditions.startTime}"))
        val end = requireNotNull(dateFormat.parse("${conditions.date} ${conditions.endTime}"))
        require(end.time - start.time in 1..43_200_000) { "여행 시간은 같은 날 최대 12시간으로 설정해 주세요." }
        require(conditions.additionalRequest.length <= 2000) { "추가 요청은 2000자 이내로 입력해 주세요." }
        return GeneratePlanRequest(
            context = PlanContext(
                area = PlanArea(center = center, radiusMeters = radiusMeters),
                origin = departure,
                destination = destination,
                startAt = "${conditions.date}T${conditions.startTime}:00+09:00",
                endAt = "${conditions.date}T${conditions.endTime}:00+09:00",
                transportMode = conditions.transportMode,
                objective = conditions.objective,
                preferences = TravelPreferences(themes = conditions.themes.map { it.label }),
                categoryRequirements = if (conditions.requireCafe) listOf(CategoryRequirement(RequiredCategory.CAFE)) else emptyList(),
                additionalRequest = conditions.additionalRequest,
                unknownHoursPolicy = conditions.unknownHoursPolicy
            ),
            requiredStops = requiredStops
        )
    }
}
