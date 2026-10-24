package com.ssafy.travelmate.screens.me

import android.Manifest
import android.annotation.SuppressLint
import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ssafy.travelmate.common.components.*
import com.ssafy.travelmate.data.remote.dto.requests.plan.*
import com.ssafy.travelmate.util.states.*
import com.ssafy.travelmate.viewmodels.search.SearchViewModel
import com.ssafy.travelmate.viewmodels.search.TravelPlanningViewModel
import java.util.Calendar
import java.util.Locale

@Composable
fun TravelPlanningScreen(
    planningViewModel: TravelPlanningViewModel,
    searchViewModel: SearchViewModel
) {
    val state by planningViewModel.state.collectAsStateWithLifecycle()
    val search by searchViewModel.searchState.collectAsStateWithLifecycle()
    val map by searchViewModel.mapState.collectAsStateWithLifecycle()
    val plan by planningViewModel.plan.collectAsStateWithLifecycle()
    val busy = state.status == PlanningStatus.SUBMITTING
    BackHandler(state.step != PlanningStep.LOCATION) { planningViewModel.back() }
    Surface(color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                if (state.step != PlanningStep.LOCATION) {
                    IconButton(onClick = planningViewModel::back, enabled = !busy) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "이전", tint = MaterialTheme.colorScheme.primary)
                    }
                } else {
                    Icon(Icons.Default.Place, null, Modifier.padding(12.dp), tint = MaterialTheme.colorScheme.primary)
                }
                Text(
                    when (state.step) {
                        PlanningStep.LOCATION -> "위치와 여행 범위"
                        PlanningStep.CONDITIONS -> "여행 조건"
                        PlanningStep.PLACES -> "장소를 하나씩 추가"
                        PlanningStep.RESULT -> "여행 일정 초안"
                    },
                    style = MaterialTheme.typography.titleMedium
                )
            }
            Column(
                Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                when (state.step) {
                    PlanningStep.LOCATION -> LocationContent(state, map, search, planningViewModel, searchViewModel)
                    PlanningStep.CONDITIONS -> ConditionsContent(state.conditions, planningViewModel::updateConditions)
                    PlanningStep.PLACES -> {
                        Text("장소를 하나씩 담기", style = MaterialTheme.typography.headlineSmall)
                        PlanningSection("공통 여행 조건") {
                            Text("${state.areaLabel} · 반경 ${state.radiusMeters / 1000f} km", style = MaterialTheme.typography.bodySmall)
                            Text("${state.conditions.date}  ${state.conditions.startTime}–${state.conditions.endTime}", style = MaterialTheme.typography.bodySmall)
                            Text(state.conditions.additionalRequest.ifBlank { "추가 요청 없음" }, style = MaterialTheme.typography.bodySmall)
                        }
                        SearchBar(
                            query = search.context.query,
                            onQueryChange = searchViewModel::updateQuery,
                            onSearch = { searchViewModel.searchWithinPlan(state.request().context) },
                            modifier = Modifier.testTag("placeSearchInput")
                        )
                        if (search.status == SearchStatus.LOADING) LinearProgressIndicator(Modifier.fillMaxWidth())
                        PlanningError(search.errorMessage)
                        if (search.status == SearchStatus.EMPTY) Text("선택한 범위에 검색 결과가 없습니다.")
                        search.places.forEach { place ->
                            val added = state.requiredStops.any { it.placeId == place.placeId }
                            PlaceResultCard(
                                place = place,
                                selected = map.selectedPlaceId == place.placeId,
                                onSelect = { searchViewModel.selectPlace(place.placeId) },
                                action = {
                                    FilledTonalButton(onClick = { planningViewModel.togglePlace(place) }) {
                                        Text(if (added) "빼기" else "+ 담기")
                                    }
                                }
                            )
                        }
                        if (state.requiredStops.isNotEmpty()) PlanningSection("내 일정 ${state.requiredStops.size}곳") {
                            state.requiredStops.forEach { stop ->
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(state.selectedPlaces.first { it.placeId == stop.placeId }.name, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                                    IconButton(onClick = { planningViewModel.changeStay(stop.placeId, stop.stayMinutes - 10) }) { Text("−") }
                                    Text("${stop.stayMinutes}분", style = MaterialTheme.typography.labelMedium)
                                    IconButton(onClick = { planningViewModel.changeStay(stop.placeId, stop.stayMinutes + 10) }) { Text("+") }
                                }
                            }
                        }
                    }
                    PlanningStep.RESULT -> {
                        Text(plan?.title.orEmpty(), style = MaterialTheme.typography.headlineSmall)
                        Box(Modifier.fillMaxWidth().height(190.dp).clip(RoundedCornerShape(16.dp))) {
                            MapContent(
                                modifier = Modifier.fillMaxSize(),
                                pins = plan?.pins.orEmpty().map { it.latitude to it.longitude },
                                onStatusChanged = searchViewModel::updateMapStatus
                            )
                        }
                        plan?.warnings?.forEach { PlanningError(it) }
                        Text("여행 조건이 서버에 저장되었습니다. 방문 순서와 체류시간을 확인해 주세요.", style = MaterialTheme.typography.bodyMedium)
                        plan?.pins?.forEach { pin ->
                            PlanningSection("${pin.sequence}. ${pin.name}") {
                                Text("체류 ${pin.stayMinutes}분 · 이동 경로와 방문 시간 확인 필요", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                PlanningError(state.errorMessage)
                Spacer(Modifier.height(4.dp))
            }
            Surface(shadowElevation = 4.dp) {
                Row(
                    Modifier.fillMaxWidth().padding(16.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    if (state.step == PlanningStep.LOCATION) {
                        Button(
                            onClick = { planningViewModel.chooseMode(PlanningMode.AI) },
                            modifier = Modifier.weight(1f).height(50.dp).testTag("chooseAi")
                        ) { Text("AI로 한 번에") }
                        OutlinedButton(
                            onClick = { planningViewModel.chooseMode(PlanningMode.MANUAL) },
                            modifier = Modifier.weight(1f).height(50.dp).testTag("chooseManual")
                        ) { Text("장소를 하나씩") }
                    } else {
                        Button(
                            enabled = !busy,
                            modifier = Modifier.fillMaxWidth().height(50.dp).testTag("planningContinue"),
                            onClick = {
                                when (state.step) {
                                    PlanningStep.CONDITIONS -> planningViewModel.continueFromConditions()
                                    PlanningStep.PLACES -> planningViewModel.submit()
                                    PlanningStep.RESULT -> planningViewModel.back()
                                    PlanningStep.LOCATION -> Unit
                                }
                            }
                        ) {
                            if (busy) {
                                CircularProgressIndicator(Modifier.size(20.dp), color = MaterialTheme.colorScheme.onPrimary, strokeWidth = 2.dp)
                                Spacer(Modifier.width(8.dp))
                                Text("여행 조건으로 처리 중…")
                            } else Text(when (state.step) {
                                PlanningStep.CONDITIONS -> if (state.mode == PlanningMode.AI) "일정 초안 만들기" else "장소 선택하기"
                                PlanningStep.PLACES -> "선택한 장소로 초안 저장"
                                else -> "조건 · 장소 다시 보기"
                            })
                        }
                    }
                }
            }
        }
    }
}

@SuppressLint("MissingPermission")
@Composable
private fun LocationContent(
    state: TravelPlanningState,
    mapState: MapState,
    searchState: SearchState,
    planningViewModel: TravelPlanningViewModel,
    searchViewModel: SearchViewModel
) {
    val context = LocalContext.current
    var locating by remember { mutableStateOf(false) }
    val locationManager = remember(context) { context.getSystemService(Context.LOCATION_SERVICE) as LocationManager }
    var activeListener by remember { mutableStateOf<android.location.LocationListener?>(null) }
    DisposableEffect(locationManager) {
        onDispose { activeListener?.let(locationManager::removeUpdates) }
    }
    LaunchedEffect(locating) {
        if (locating) {
            kotlinx.coroutines.delay(15_000)
            activeListener?.let(locationManager::removeUpdates)
            locating = false
            planningViewModel.showError("현재 위치를 확인하지 못했습니다. 다시 시도하거나 지도에서 선택해 주세요.")
        }
    }
    val requestLocation = {
        val manager = locationManager
        val provider = listOf(LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER)
            .firstOrNull { manager.isProviderEnabled(it) }
        if (provider == null) {
            planningViewModel.showError("휴대폰 위치 서비스를 켜거나 원하는 위치를 지도에서 선택해 주세요.")
        } else {
            activeListener?.let(manager::removeUpdates)
            locating = true
            val listener = object : android.location.LocationListener {
                override fun onLocationChanged(location: android.location.Location) {
                    locating = false
                    planningViewModel.selectLocation(Coordinate(location.latitude, location.longitude), "현재 위치", LocationSource.GPS)
                }
                override fun onProviderDisabled(provider: String) {
                    locating = false
                    planningViewModel.showError("현재 위치를 확인할 수 없습니다.")
                }
                override fun onProviderEnabled(provider: String) = Unit
                @Deprecated("Deprecated in Android")
                override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit
            }
            activeListener = listener
            @Suppress("DEPRECATION")
            manager.requestSingleUpdate(provider, listener, android.os.Looper.getMainLooper())
        }
    }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        if (granted.values.any { it }) requestLocation()
        else planningViewModel.showError("위치 권한이 없어 현재 위치를 가져올 수 없습니다. 지도에서 원하는 위치를 선택해 주세요.")
    }
    Text("어디를 여행할까요?", style = MaterialTheme.typography.headlineSmall)
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        FilterChip(
            selected = state.locationChoice == LocationChoice.CURRENT,
            onClick = {
                planningViewModel.chooseLocation(LocationChoice.CURRENT)
                if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED) requestLocation()
                else permissionLauncher.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
            },
            label = { Text(if (locating) "위치 확인 중…" else "현재 위치") }
        )
        FilterChip(
            selected = state.locationChoice == LocationChoice.SELECTED,
            onClick = { planningViewModel.chooseLocation(LocationChoice.SELECTED) },
            label = { Text("원하는 위치") }
        )
    }
    SearchBar(
        query = searchState.context.query,
        onQueryChange = searchViewModel::updateQuery,
        onSearch = { searchViewModel.searchLocations() },
        modifier = Modifier.testTag("placeSearchInput")
    )
    if (searchState.status == SearchStatus.LOADING) LinearProgressIndicator(Modifier.fillMaxWidth())
    PlanningError(searchState.errorMessage)
    searchState.places.take(3).forEach { place ->
        TextButton(onClick = {
            val latitude = place.latitude
            val longitude = place.longitude
            if (latitude != null && longitude != null) {
                planningViewModel.selectLocation(Coordinate(latitude, longitude), place.name)
                searchViewModel.selectPlace(place.placeId)
            }
        }) { Icon(Icons.Default.Place, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text(place.name) }
    }
    Box(Modifier.fillMaxWidth().height(210.dp).clip(RoundedCornerShape(16.dp)).testTag("locationMap")) {
        MapContent(
            modifier = Modifier.fillMaxSize(),
            pins = listOfNotNull(state.areaCenter?.let { it.lat to it.lon }),
            places = searchState.places,
            selectedPlaceId = mapState.selectedPlaceId,
            focusCoordinate = state.areaCenter,
            radiusMeters = state.radiusMeters,
            onPinAdded = { latitude, longitude ->
                planningViewModel.selectLocation(Coordinate(latitude, longitude), "지도에서 선택한 위치")
            },
            onPlaceSelected = { placeId ->
                searchViewModel.selectPlace(placeId)
                searchState.places.firstOrNull { it.placeId == placeId }?.let { place ->
                    if (place.latitude != null && place.longitude != null) planningViewModel.selectLocation(Coordinate(place.latitude, place.longitude), place.name)
                }
            },
            onStatusChanged = searchViewModel::updateMapStatus
        )
    }
    if (mapState.status == MapStatus.ERROR) PlanningError("지도를 불러오지 못했습니다. 네트워크 연결을 확인해 주세요.")
    Text(
        "지도를 길게 눌러 ${when (state.locationTarget) { LocationTarget.AREA -> "여행할 위치"; LocationTarget.ORIGIN -> "출발 지점"; LocationTarget.DESTINATION -> "마지막 도착지" }}를 선택하세요.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
    Column {
        Text("주변 ${String.format(Locale.KOREA, "%.1f", state.radiusMeters / 1000f)} km", style = MaterialTheme.typography.titleSmall)
        Slider(
            value = state.radiusMeters.toFloat(),
            onValueChange = { planningViewModel.changeRadius((it / 500).toInt() * 500) },
            valueRange = 500f..10000f,
            steps = 18
        )
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("0.5 km", style = MaterialTheme.typography.labelSmall)
            Text("10 km", style = MaterialTheme.typography.labelSmall)
        }
    }
    LocationTarget.entries.forEach { target ->
        val label = when (target) {
            LocationTarget.AREA -> "여행 범위  ·  ${state.areaLabel}"
            LocationTarget.ORIGIN -> "출발 지점  ·  ${state.origin?.label ?: "선택 필요"}"
            LocationTarget.DESTINATION -> "마지막 도착지  ·  ${state.destination?.label ?: "선택 사항"}"
        }
        OutlinedButton(
            onClick = { planningViewModel.targetLocation(target) },
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(10.dp),
            colors = ButtonDefaults.outlinedButtonColors(containerColor = if (state.locationTarget == target) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface)
        ) { Text(label, style = MaterialTheme.typography.bodySmall) }
    }
    if (state.destination != null) TextButton(onClick = planningViewModel::clearDestination) { Text("도착지 선택 해제") }
}

@Composable
private fun ConditionsContent(
    conditions: TravelConditions,
    onChange: (TravelConditions) -> Unit
) {
    val context = LocalContext.current
    Text("여행 조건", style = MaterialTheme.typography.headlineSmall)
    PlanningSection("여행 날짜 · 시간") {
        OutlinedButton(onClick = {
            val parts = conditions.date.split('-').map { it.toInt() }
            DatePickerDialog(context, { _, year, month, day ->
                onChange(conditions.copy(date = String.format(Locale.ROOT, "%04d-%02d-%02d", year, month + 1, day)))
            }, parts[0], parts[1] - 1, parts[2]).show()
        }, modifier = Modifier.fillMaxWidth()) { Text(conditions.date) }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            listOf(true, false).forEach { isStart ->
                val time = if (isStart) conditions.startTime else conditions.endTime
                OutlinedButton(onClick = {
                    val parts = time.split(':').map { it.toInt() }
                    TimePickerDialog(context, { _, hour, minute ->
                        val selected = String.format(Locale.ROOT, "%02d:%02d", hour, minute)
                        onChange(if (isStart) conditions.copy(startTime = selected) else conditions.copy(endTime = selected))
                    }, parts[0], parts[1], true).show()
                }, modifier = Modifier.weight(1f)) { Text("${if (isStart) "시작" else "종료"} $time") }
            }
        }
    }
    PlanningSection("이동 수단") {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            TransportMode.entries.forEach { mode ->
                FilterChip(selected = conditions.transportMode == mode, onClick = { onChange(conditions.copy(transportMode = mode)) }, label = { Text(if (mode == TransportMode.WALK) "도보" else "자동차") })
            }
        }
    }
    PlanningSection("일정 최적화 기준") {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PlanObjective.entries.forEach { objective ->
                FilterChip(selected = conditions.objective == objective, onClick = { onChange(conditions.copy(objective = objective)) }, label = { Text(if (objective == PlanObjective.DISTANCE) "짧은 거리" else "짧은 이동시간") })
            }
        }
    }
    PlanningSection("관심 테마 · 복수 선택 가능") {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TravelTheme.entries.forEach { theme ->
                FilterChip(
                    selected = theme in conditions.themes,
                    onClick = { onChange(conditions.copy(themes = if (theme in conditions.themes) conditions.themes - theme else conditions.themes + theme)) },
                    label = { Text(theme.label) }
                )
            }
        }
    }
    PlanningSection("추가 요청 사항") {
        OutlinedTextField(
            value = conditions.additionalRequest,
            onValueChange = { if (it.length <= 2000) onChange(conditions.copy(additionalRequest = it)) },
            placeholder = { Text("조용한 곳 위주, 카페 1곳 이상", style = MaterialTheme.typography.bodySmall) },
            modifier = Modifier.fillMaxWidth().testTag("additionalRequest"),
            shape = RoundedCornerShape(10.dp),
            minLines = 2,
            maxLines = 4
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = conditions.requireCafe, onCheckedChange = { onChange(conditions.copy(requireCafe = it)) })
            Text("카페 1곳 이상", style = MaterialTheme.typography.bodyMedium)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(
                modifier = Modifier.testTag("includeUnknownHours"),
                checked = conditions.unknownHoursPolicy == UnknownHoursPolicy.ALLOW_WITH_WARNING,
                onCheckedChange = { onChange(conditions.copy(unknownHoursPolicy = if (it) UnknownHoursPolicy.ALLOW_WITH_WARNING else UnknownHoursPolicy.EXCLUDE)) }
            )
            Text("운영시간 미확인 장소 포함", style = MaterialTheme.typography.bodySmall)
        }
    }
}
