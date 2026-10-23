package com.ssafy.travelmate.common.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ssafy.travelmate.util.states.MapState
import com.ssafy.travelmate.util.states.MapStatus
import com.ssafy.travelmate.util.states.SearchState

@Composable
fun MapSearchContent(
    searchState: SearchState,
    mapState: MapState,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
    onPlaceSelected: (Long) -> Unit,
    onPinAdded: (Double, Double) -> Unit,
    onMapStatusChanged: (MapStatus) -> Unit,
    modifier: Modifier = Modifier
) {
    Box(modifier = modifier.fillMaxSize()) {
        MapContent(
            modifier = Modifier.fillMaxSize(),
            pins = mapState.personalPins,
            places = searchState.places,
            selectedPlaceId = mapState.selectedPlaceId,
            onPinAdded = onPinAdded,
            onPlaceSelected = onPlaceSelected,
            onStatusChanged = onMapStatusChanged
        )
        SearchContent(
            searchState = searchState,
            mapState = mapState,
            onQueryChange = onQueryChange,
            onSearch = onSearch,
            onPlaceSelected = onPlaceSelected
        )
    }
}
