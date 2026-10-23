package com.ssafy.travelmate.search

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performImeAction
import androidx.compose.ui.test.performTextInput
import androidx.test.platform.app.InstrumentationRegistry
import com.ssafy.travelmate.common.components.MapSearchContent
import com.ssafy.travelmate.common.components.SearchContent
import com.ssafy.travelmate.apis.PlaceSearchApi
import com.ssafy.travelmate.base.MainApplication
import com.ssafy.travelmate.repositories.PlaceSearchRepository
import okhttp3.OkHttpClient
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit
import com.ssafy.travelmate.di.AppModule
import com.ssafy.travelmate.ui.theme.TravelMateTheme
import com.ssafy.travelmate.util.states.MapStatus
import com.ssafy.travelmate.util.states.SearchStatus
import com.ssafy.travelmate.viewmodels.search.SearchViewModel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test

class PlaceSearchE2ETest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun liveSemanticSearchShowsResultsAndSelectsMapPin() {
        val arguments = InstrumentationRegistry.getArguments()
        assumeTrue("실제 백엔드와 Kakao 인증이 필요한 테스트", arguments.getString("liveSearchE2E") == "true")
        val query = requireNotNull(arguments.getString("searchQuery")) {
            "검색 데이터에 맞는 searchQuery를 지정하세요."
        }
        val viewModel = createViewModel()
        compose.setContent {
            val searchState by viewModel.searchState.collectAsState()
            val mapState by viewModel.mapState.collectAsState()
            TravelMateTheme(dynamicColor = false) {
                MapSearchContent(
                    searchState = searchState,
                    mapState = mapState,
                    onQueryChange = viewModel::updateQuery,
                    onSearch = { viewModel.search() },
                    onPlaceSelected = viewModel::selectPlace,
                    onPinAdded = viewModel::addPersonalPin,
                    onMapStatusChanged = viewModel::updateMapStatus
                )
            }
        }
        compose.onNodeWithTag("placeSearchInput").performTextInput(query)
        compose.onNodeWithTag("placeSearchInput").performImeAction()
        compose.waitUntil(timeoutMillis = 95_000) {
            viewModel.searchState.value.status in setOf(SearchStatus.SUCCESS, SearchStatus.EMPTY, SearchStatus.ERROR)
        }
        assertEquals(SearchStatus.SUCCESS, viewModel.searchState.value.status)
        assertTrue(viewModel.searchState.value.places.isNotEmpty())
        compose.waitUntil(timeoutMillis = 30_000) { viewModel.mapState.value.status != MapStatus.LOADING }
        assertEquals(MapStatus.READY, viewModel.mapState.value.status)
        val placeId = viewModel.searchState.value.places.first().placeId
        compose.onNodeWithTag("place-$placeId").performClick().assertIsSelected()
        assertEquals(placeId, viewModel.mapState.value.selectedPlaceId)
    }

    @Test
    fun liveSemanticSearchReturnsSelectableResults() {
        val arguments = InstrumentationRegistry.getArguments()
        assumeTrue(arguments.getString("liveSearchE2E") == "true")
        val query = requireNotNull(arguments.getString("searchQuery"))
        val viewModel = createViewModel()
        compose.setContent {
            val searchState by viewModel.searchState.collectAsState()
            val mapState by viewModel.mapState.collectAsState()
            TravelMateTheme(dynamicColor = false) {
                SearchContent(
                    searchState = searchState,
                    mapState = mapState,
                    onQueryChange = viewModel::updateQuery,
                    onSearch = { viewModel.search() },
                    onPlaceSelected = viewModel::selectPlace
                )
            }
        }
        compose.onNodeWithTag("placeSearchInput").performTextInput(query)
        compose.onNodeWithTag("placeSearchInput").performImeAction()
        compose.waitUntil(timeoutMillis = 95_000) {
            viewModel.searchState.value.status in setOf(SearchStatus.SUCCESS, SearchStatus.EMPTY, SearchStatus.ERROR)
        }
        assertEquals(SearchStatus.SUCCESS, viewModel.searchState.value.status)
        val places = viewModel.searchState.value.places
        assertTrue(places.isNotEmpty())
        assertTrue(places.zipWithNext().all { (first, second) -> first.rerankScore >= second.rerankScore })
        compose.onNodeWithTag("place-${places.first().placeId}").performClick().assertIsSelected()
        assertEquals(places.first().placeId, viewModel.mapState.value.selectedPlaceId)
    }

    private fun createViewModel(): SearchViewModel {
        val arguments = InstrumentationRegistry.getArguments()
        val fixtureName = arguments.getString("searchAuthFixture")
        if (fixtureName == null) {
            return SearchViewModel(AppModule.providePlaceSearchRepository(AppModule.providePlaceSearchApi()))
        }
        require(fixtureName.matches(Regex("[a-zA-Z0-9_-]+\\.json")))
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val fixture = File(context.filesDir, fixtureName)
        val accessToken = JSONObject(fixture.readText()).getString("accessToken")
        // 테스트 계정의 토큰은 개인 앱 로그인 상태를 변경하지 않고 해당 요청에만 사용한다.
        val retrofit = MainApplication.retrofit
        val client = (retrofit.callFactory() as OkHttpClient).newBuilder()
            .readTimeout(60, TimeUnit.SECONDS)
            .callTimeout(90, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                chain.proceed(chain.request().newBuilder().header("Authorization", "Bearer $accessToken").build())
            }
            .build()
        val api = retrofit.newBuilder().client(client).build().create(PlaceSearchApi::class.java)
        return SearchViewModel(PlaceSearchRepository(api))
    }
}
