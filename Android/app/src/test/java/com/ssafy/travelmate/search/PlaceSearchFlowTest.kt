package com.ssafy.travelmate.search

import com.google.gson.Gson
import com.ssafy.travelmate.apis.PlaceSearchApi
import com.ssafy.travelmate.repositories.PlaceSearchRepository
import com.ssafy.travelmate.util.states.SearchContext
import com.ssafy.travelmate.util.states.SearchStatus
import com.ssafy.travelmate.viewmodels.search.SearchViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

@OptIn(ExperimentalCoroutinesApi::class)
class PlaceSearchFlowTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: SearchViewModel

    @Before
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        server = MockWebServer().apply { start() }
        val api = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(PlaceSearchApi::class.java)
        viewModel = SearchViewModel(PlaceSearchRepository(api))
    }

    @After
    fun tearDown() {
        viewModel.updateQuery("")
        server.shutdown()
        Dispatchers.resetMain()
    }

    @Test
    fun filtersAndUnicodeQueryReachApiAndResultSelectsMapPin() = runBlocking {
        val context = SearchContext(
            query = "  역사 공부하고 싶어  ",
            region = "서울",
            city = "종로구",
            category = "문화시설",
            limit = 5
        )
        server.enqueue(placeResponse(41L))
        viewModel.search(context)
        awaitStatus(SearchStatus.SUCCESS)

        val request = server.takeRequest(2, TimeUnit.SECONDS)!!
        assertEquals("/api/places/search", request.requestUrl!!.encodedPath)
        assertEquals(context.query.trim(), request.requestUrl!!.queryParameter("query"))
        assertEquals(context.region, request.requestUrl!!.queryParameter("region"))
        assertEquals(context.city, request.requestUrl!!.queryParameter("city"))
        assertEquals(context.category, request.requestUrl!!.queryParameter("category"))
        assertEquals("5", request.requestUrl!!.queryParameter("limit"))
        assertEquals(41L, viewModel.searchState.value.places.single().placeId)
        viewModel.selectPlace(41L)
        assertEquals(41L, viewModel.mapState.value.selectedPlaceId)
        viewModel.selectPlace(999L)
        assertEquals(41L, viewModel.mapState.value.selectedPlaceId)
    }

    @Test
    fun emptyResultsAndHttpFailuresHaveDifferentStatesAndRetryRecovers() = runBlocking {
        server.enqueue(MockResponse().setBody("[]"))
        viewModel.search(SearchContext(query = "없는 장소"))
        awaitStatus(SearchStatus.EMPTY)
        server.enqueue(MockResponse().setResponseCode(503))
        viewModel.search()
        awaitStatus(SearchStatus.ERROR)
        assertNotNull(viewModel.searchState.value.errorMessage)
        server.enqueue(placeResponse(52L))
        viewModel.search()
        awaitStatus(SearchStatus.SUCCESS)
        assertNull(viewModel.searchState.value.errorMessage)
    }

    @Test
    fun malformedResponseDoesNotAppearAsEmptySuccess() = runBlocking {
        server.enqueue(MockResponse().setBody("not-json"))
        viewModel.search(SearchContext(query = "공원"))
        awaitStatus(SearchStatus.ERROR)
    }

    @Test
    fun editingQueryCancelsOldResultsAndKeepsPersonalPins() = runBlocking {
        server.enqueue(placeResponse(63L).setBodyDelay(300, TimeUnit.MILLISECONDS))
        viewModel.addPersonalPin(37.5, 127.0)
        viewModel.search(SearchContext(query = "이전 검색"))
        assertNotNull(server.takeRequest(2, TimeUnit.SECONDS))
        viewModel.updateQuery("새 검색")
        server.enqueue(placeResponse(74L))
        viewModel.search()
        awaitStatus(SearchStatus.SUCCESS)
        assertEquals(74L, viewModel.searchState.value.places.single().placeId)
        assertEquals("새 검색", viewModel.searchState.value.context.query)
        assertEquals(listOf(37.5 to 127.0), viewModel.mapState.value.personalPins)
        viewModel.updateQuery("")
        viewModel.search()
        assertEquals(SearchStatus.IDLE, viewModel.searchState.value.status)
        assertTrue(viewModel.searchState.value.places.isEmpty())
        assertNull(viewModel.mapState.value.selectedPlaceId)
        assertEquals(2, server.requestCount)
    }

    private suspend fun awaitStatus(status: SearchStatus) {
        withTimeout(5_000) { viewModel.searchState.first { it.status == status } }
    }

    private fun placeResponse(placeId: Long): MockResponse {
        val place = mapOf(
            "placeId" to placeId,
            "name" to "역사 전시관",
            "latitude" to 37.57,
            "longitude" to 126.98,
            "semanticScore" to 0.7,
            "rerankScore" to 0.8
        )
        return MockResponse()
            .setHeader("Content-Type", "application/json")
            .setBody(Gson().toJson(listOf(place)))
    }
}
