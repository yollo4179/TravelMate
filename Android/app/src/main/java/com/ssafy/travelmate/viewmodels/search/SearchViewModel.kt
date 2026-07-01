package com.ssafy.travelmate.viewmodels.search

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceResponse
import com.ssafy.travelmate.repositories.KakaoQueryRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

private const val TAG = "SearchViewModel"

@HiltViewModel
class SearchViewModel @Inject constructor(
    private val kakaoQueryRepository: KakaoQueryRepository
) : ViewModel() {

    private val _places = MutableStateFlow<List<PlaceResponse>>(emptyList())
    val places: StateFlow<List<PlaceResponse>> = _places.asStateFlow()

    fun fetchPlaces(query: String) {
        if (query.isBlank()) {
            _places.value = emptyList()
            return
        }
        viewModelScope.launch {
            try {
                val result = kakaoQueryRepository.searchPlaces(query).getOrThrow()
                _places.value = result
            } catch (e: Exception) {
                Log.w(TAG, "장소 검색 실패: ${e.message}")
                _places.value = emptyList()
            }
        }
    }
}
