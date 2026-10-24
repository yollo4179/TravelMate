package com.ssafy.travelmate.search

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.ssafy.travelmate.apis.PlanApi
import com.ssafy.travelmate.apis.PlaceSearchApi
import com.ssafy.travelmate.base.MainApplication
import com.ssafy.travelmate.data.remote.dto.requests.plan.Coordinate
import com.ssafy.travelmate.repositories.PlaceSearchRepository
import com.ssafy.travelmate.repositories.TravelPlanningRepository
import com.ssafy.travelmate.screens.me.TravelPlanningScreen
import com.ssafy.travelmate.ui.theme.TravelMateTheme
import com.ssafy.travelmate.util.states.PlanningStep
import com.ssafy.travelmate.util.states.PlanningStatus
import com.ssafy.travelmate.util.states.SearchStatus
import com.ssafy.travelmate.viewmodels.search.SearchViewModel
import com.ssafy.travelmate.viewmodels.search.TravelPlanningViewModel
import okhttp3.OkHttpClient
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import java.io.File
import java.util.concurrent.TimeUnit

class TravelPlanningE2ETest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun manualFlowSendsConditionsAndSelectedStopsToRealServer() {
        val arguments = InstrumentationRegistry.getArguments()
        assumeTrue(arguments.getString("livePlanningE2E") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val fixtureName = requireNotNull(arguments.getString("searchAuthFixture"))
        require(fixtureName.matches(Regex("[a-zA-Z0-9_-]+\\.json")))
        val fixture = JSONObject(File(instrumentation.targetContext.filesDir, fixtureName).readText())
        val token = fixture.getString("accessToken")
        val original = MainApplication.retrofit
        val client = (original.callFactory() as OkHttpClient).newBuilder()
            .readTimeout(60, TimeUnit.SECONDS)
            .callTimeout(90, TimeUnit.SECONDS)
            .addInterceptor { chain -> chain.proceed(chain.request().newBuilder().header("Authorization", "Bearer $token").build()) }
            .build()
        val retrofit = original.newBuilder().client(client).build()
        val planning = TravelPlanningViewModel(TravelPlanningRepository(retrofit.create(PlanApi::class.java)))
        val search = SearchViewModel(PlaceSearchRepository(retrofit.create(PlaceSearchApi::class.java)))
        planning.selectLocation(Coordinate(fixture.getDouble("latitude"), fixture.getDouble("longitude")), "검증 출발지")
        compose.setContent { TravelMateTheme(dynamicColor = false) { TravelPlanningScreen(planning, search) } }
        compose.onNodeWithTag("chooseManual").performClick()
        assertEquals(PlanningStep.CONDITIONS, planning.state.value.step)
        compose.onNodeWithTag("additionalRequest").performScrollTo().performTextInput("조용한 산책 장소")
        compose.onNodeWithTag("includeUnknownHours").performScrollTo().performClick()
        compose.onNodeWithTag("planningContinue").performClick()
        assertEquals(PlanningStep.PLACES, planning.state.value.step)
        compose.onNodeWithTag("placeSearchInput").performScrollTo().performTextInput("공원")
        compose.onNodeWithTag("placeSearchInput").performImeAction()
        compose.waitUntil(95_000) { search.searchState.value.status in setOf(SearchStatus.SUCCESS, SearchStatus.ERROR, SearchStatus.EMPTY) }
        assertEquals(SearchStatus.SUCCESS, search.searchState.value.status)
        compose.onAllNodesWithText("+ 담기").onFirst().performScrollTo().performClick()
        val expected = planning.state.value.request()
        assertEquals(1, expected.requiredStops.size)
        compose.onNodeWithTag("planningContinue").performClick()
        compose.waitUntil(30_000) { planning.state.value.status in setOf(PlanningStatus.SUCCESS, PlanningStatus.ERROR) }
        assertEquals(planning.state.value.errorMessage, PlanningStatus.SUCCESS, planning.state.value.status)
        assertEquals(PlanningStep.RESULT, planning.state.value.step)
        assertEquals(expected.context, planning.plan.value!!.context)
        assertEquals(expected.requiredStops.single().placeId, planning.plan.value!!.pins.single().placeId)
    }
}
