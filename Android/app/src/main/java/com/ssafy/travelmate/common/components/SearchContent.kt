package com.ssafy.travelmate.common.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ssafy.travelmate.util.states.MapState
import com.ssafy.travelmate.util.states.MapStatus
import com.ssafy.travelmate.util.states.SearchState
import com.ssafy.travelmate.util.states.SearchStatus

@Composable
fun SearchContent(
    searchState: SearchState,
    mapState: MapState,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
    onPlaceSelected: (Long) -> Unit,
    modifier: Modifier = Modifier
) {
    Box(modifier = modifier.fillMaxSize()) {
        SearchBar(
            query = searchState.context.query,
            onQueryChange = onQueryChange,
            onSearch = { onSearch() },
            modifier = Modifier.align(Alignment.TopCenter).testTag("placeSearchInput")
        )
        Column(modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth()) {
            if (mapState.status == MapStatus.ERROR) {
                Surface { Text("지도를 불러오지 못했습니다. 검색 결과는 목록에서 확인할 수 있습니다.", Modifier.padding(16.dp)) }
            }
            when (searchState.status) {
                SearchStatus.IDLE -> Unit
                SearchStatus.LOADING -> LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                SearchStatus.EMPTY -> Surface {
                    Text("검색 결과가 없습니다. 다른 검색어로 시도해 주세요.", Modifier.padding(16.dp))
                }
                SearchStatus.ERROR -> Surface {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(searchState.errorMessage.orEmpty(), Modifier.weight(1f).padding(16.dp))
                        TextButton(onClick = onSearch) { Text("재시도") }
                    }
                }
                SearchStatus.SUCCESS -> Surface {
                    LazyColumn(modifier = Modifier.fillMaxWidth().heightIn(max = 240.dp).testTag("placeSearchResults")) {
                        items(searchState.places, key = { it.placeId }) { place ->
                            ListItem(
                                headlineContent = { Text(place.name) },
                                supportingContent = {
                                    Text(listOfNotNull(place.region, place.city, place.category).joinToString(" · "))
                                },
                                modifier = Modifier
                                    .testTag("place-${place.placeId}")
                                    .semantics { selected = place.placeId == mapState.selectedPlaceId }
                                    .clickable { onPlaceSelected(place.placeId) }
                            )
                        }
                    }
                }
            }
        }
    }
}
