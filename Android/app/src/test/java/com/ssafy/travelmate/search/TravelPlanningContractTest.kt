package com.ssafy.travelmate.search

import com.google.gson.Gson
import com.google.gson.JsonParser
import com.ssafy.travelmate.apis.PlanApi
import com.ssafy.travelmate.data.remote.dto.requests.plan.*
import com.ssafy.travelmate.repositories.TravelPlanningRepository
import com.ssafy.travelmate.util.states.*
import com.ssafy.travelmate.viewmodels.search.TravelPlanningViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

@OptIn(ExperimentalCoroutinesApi::class)
class TravelPlanningContractTest {
    private fun state() = TravelPlanningState(
        areaCenter = Coordinate(35.8395, 129.212),
        origin = PlanLocation(Coordinate(35.8401, 129.214), "출발지", LocationSource.SELECTED_POINT),
        destination = PlanLocation(Coordinate(35.84, 129.21), "도착지", LocationSource.SELECTED_POINT),
        conditions = TravelConditions(
            date = "2026-10-20",
            themes = setOf(TravelTheme.CULTURE, TravelTheme.WALK),
            additionalRequest = "조용한 곳 위주, 카페 한 곳 이상",
            requireCafe = true,
            unknownHoursPolicy = UnknownHoursPolicy.ALLOW_WITH_WARNING
        ),
        requiredStops = listOf(RequiredStop(101, 60))
    )

    @Test
    fun requestMatchesPdfContextAndKeepsDepartureSeparateFromArea() {
        val request = state().request()
        val json = JsonParser.parseString(Gson().toJson(request)).asJsonObject
        assertEquals(setOf("context", "inputMethod", "requiredStops"), json.keySet())
        val context = json.getAsJsonObject("context")
        assertEquals(3000, context.getAsJsonObject("area").get("radiusMeters").asInt)
        assertEquals(35.8395, context.getAsJsonObject("area").getAsJsonObject("center").get("lat").asDouble, 0.00001)
        assertEquals(35.8401, context.getAsJsonObject("origin").getAsJsonObject("coordinate").get("lat").asDouble, 0.00001)
        assertEquals("2026-10-20T10:00:00+09:00", context.get("startAt").asString)
        assertEquals("CAFE", context.getAsJsonArray("categoryRequirements")[0].asJsonObject.get("category").asString)
        assertEquals("TEXT", json.get("inputMethod").asString)
        assertEquals(60, json.getAsJsonArray("requiredStops")[0].asJsonObject.get("stayMinutes").asInt)
    }

    @Test
    fun bothModesRequireLocationAndPassThroughConditionsWithoutLosingInputs() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        try {
            MockWebServer().use { server ->
                val api = Retrofit.Builder().baseUrl(server.url("/"))
                    .addConverterFactory(GsonConverterFactory.create()).build().create(PlanApi::class.java)
                PlanningMode.entries.forEach { mode ->
                    val viewModel = TravelPlanningViewModel(TravelPlanningRepository(api))
                    viewModel.chooseMode(mode)
                    assertEquals(PlanningStep.LOCATION, viewModel.state.value.step)
                    viewModel.selectLocation(Coordinate(37.5665, 126.978), "서울시청")
                    viewModel.updateConditions(state().conditions)
                    viewModel.chooseMode(mode)
                    assertEquals(PlanningStep.CONDITIONS, viewModel.state.value.step)
                    assertEquals(state().conditions, viewModel.state.value.conditions)
                    viewModel.back()
                    assertEquals(state().conditions, viewModel.state.value.conditions)
                }
            }
        } finally { Dispatchers.resetMain() }
    }

    @Test
    fun generationPostsFullJsonAndUsesIdempotencyHeader() = runBlocking {
        MockWebServer().use { server ->
            val request = state().request()
            server.enqueue(MockResponse().setBody("""{"jobId":"job","status":"SUCCEEDED","statusUrl":"/api/v1/planning-jobs/job","planId":42}"""))
            server.enqueue(MockResponse().setBody("""{"planId":42,"context":${Gson().toJson(request.context)},"title":"여행","pins":[],"warnings":[]}"""))
            val api = Retrofit.Builder().baseUrl(server.url("/"))
                .addConverterFactory(GsonConverterFactory.create()).build().create(PlanApi::class.java)
            val result = TravelPlanningRepository(api).submit(request, PlanningMode.AI, "same-action-key")
            val outgoing = server.takeRequest()
            assertEquals("POST", outgoing.method)
            assertEquals("/api/v1/plans/generations", outgoing.path)
            assertEquals("same-action-key", outgoing.getHeader("Idempotency-Key"))
            assertEquals(JsonParser.parseString(Gson().toJson(request)), JsonParser.parseString(outgoing.body.readUtf8()))
            assertEquals(request.context, result.context)
        }
    }

    @Test
    fun invalidTimeWindowCannotBecomeServerRequest() {
        listOf("09:00", "23:00").forEach { endTime ->
            assertThrows(IllegalArgumentException::class.java) {
                state().copy(conditions = state().conditions.copy(endTime = endTime)).request()
            }
        }
    }
}
