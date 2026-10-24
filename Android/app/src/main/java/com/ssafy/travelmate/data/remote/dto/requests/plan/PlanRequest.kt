package com.ssafy.travelmate.data.remote.dto.requests.plan

enum class AreaType { CIRCLE, REGION }
enum class LocationSource { GPS, SELECTED_POINT }
enum class TransportMode { WALK, CAR }
enum class PlanObjective { DISTANCE, DURATION }
enum class TravelPace { RELAXED, NORMAL }
enum class UnknownHoursPolicy { EXCLUDE, ALLOW_WITH_WARNING }
enum class InputMethod { TEXT, VOICE }
enum class RequiredCategory { CAFE }

data class Coordinate(val lat: Double, val lon: Double)

data class PlanArea(
    val type: AreaType = AreaType.CIRCLE,
    val center: Coordinate,
    val radiusMeters: Int = 3000,
    val regionId: String? = null
)

data class PlanLocation(
    val coordinate: Coordinate,
    val label: String,
    val source: LocationSource
)

data class TravelPreferences(
    val themes: List<String> = emptyList(),
    val avoid: List<String> = emptyList(),
    val pace: TravelPace = TravelPace.RELAXED,
    val partySize: Int = 1,
    val budgetKrw: Long? = null
)

data class CategoryRequirement(
    val category: RequiredCategory,
    val minCount: Int = 1
)

data class PlanContext(
    val area: PlanArea,
    val origin: PlanLocation,
    val destination: PlanLocation? = null,
    val startAt: String,
    val endAt: String,
    val transportMode: TransportMode = TransportMode.WALK,
    val objective: PlanObjective = PlanObjective.DISTANCE,
    val preferences: TravelPreferences = TravelPreferences(),
    val categoryRequirements: List<CategoryRequirement> = emptyList(),
    val additionalRequest: String = "",
    val unknownHoursPolicy: UnknownHoursPolicy = UnknownHoursPolicy.EXCLUDE
)

data class RequiredStop(
    val placeId: Long,
    val stayMinutes: Int = 40,
    val fixedStartAt: String? = null
)

data class GeneratePlanRequest(
    val context: PlanContext,
    val inputMethod: InputMethod = InputMethod.TEXT,
    val requiredStops: List<RequiredStop> = emptyList()
)

data class ContextPlaceSearchRequest(
    val context: PlanContext,
    val query: String,
    val limit: Int = 10
)
