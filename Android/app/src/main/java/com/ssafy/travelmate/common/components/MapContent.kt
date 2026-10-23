package com.ssafy.travelmate.common.components

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.kakao.vectormap.KakaoMap
import com.kakao.vectormap.KakaoMapReadyCallback
import com.kakao.vectormap.LatLng
import com.kakao.vectormap.MapLifeCycleCallback
import com.kakao.vectormap.MapView
import com.kakao.vectormap.camera.CameraUpdateFactory
import com.kakao.vectormap.label.LabelOptions
import com.kakao.vectormap.label.LabelStyle
import com.kakao.vectormap.label.LabelStyles
import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceSearchResponse
import com.ssafy.travelmate.util.states.MapStatus

@Composable
fun MapContent(
    modifier: Modifier,
    pins: List<Pair<Double, Double>> = emptyList(),
    places: List<PlaceSearchResponse> = emptyList(),
    selectedPlaceId: Long? = null,
    focusCoordinate: com.ssafy.travelmate.data.remote.dto.requests.plan.Coordinate? = null,
    radiusMeters: Int? = null,
    onPinAdded: (Double, Double) -> Unit = { _, _ -> },
    onPlaceSelected: (Long) -> Unit = {},
    onStatusChanged: (MapStatus) -> Unit = {}
) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val mapView = remember(context) { MapView(context) }
    var kakaoMap by remember { mutableStateOf<KakaoMap?>(null) }
    val currentOnPinAdded by rememberUpdatedState(onPinAdded)
    val currentOnPlaceSelected by rememberUpdatedState(onPlaceSelected)
    val currentOnStatusChanged by rememberUpdatedState(onStatusChanged)

    DisposableEffect(mapView, lifecycle) {
        currentOnStatusChanged(MapStatus.LOADING)
        mapView.start(
            object : MapLifeCycleCallback() {
                override fun onMapDestroy() { kakaoMap = null }
                override fun onMapError(error: Exception) {
                    currentOnStatusChanged(MapStatus.ERROR)
                }
            },
            object : KakaoMapReadyCallback() {
                override fun getPosition(): LatLng = LatLng.from(37.5665, 126.9780)
                override fun onMapReady(map: KakaoMap) {
                    kakaoMap = map
                    map.setOnLabelClickListener { _, _, label ->
                        val placeId = label.tag as? Long
                        if (placeId != null) currentOnPlaceSelected(placeId)
                        placeId != null
                    }
                    map.setOnTerrainLongClickListener { _, position, _ ->
                        currentOnPinAdded(position.latitude, position.longitude)
                    }
                    currentOnStatusChanged(MapStatus.READY)
                }
            }
        )
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> mapView.resume()
                Lifecycle.Event.ON_PAUSE -> mapView.pause()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) mapView.resume()
        onDispose {
            lifecycle.removeObserver(observer)
            mapView.finish()
            kakaoMap = null
        }
    }

    LaunchedEffect(kakaoMap, pins, places, selectedPlaceId) {
        val layer = kakaoMap?.labelManager?.layer ?: return@LaunchedEffect
        layer.removeAll()
        val defaultStyle = LabelStyles.from(LabelStyle.from(android.R.drawable.ic_menu_mylocation))
        val selectedStyle = LabelStyles.from(LabelStyle.from(android.R.drawable.star_big_on))
        pins.forEach { (latitude, longitude) ->
            layer.addLabel(LabelOptions.from(LatLng.from(latitude, longitude)).setStyles(defaultStyle))
        }
        places.forEach { place ->
            val position = place.mapPosition() ?: return@forEach
            layer.addLabel(
                LabelOptions.from(position)
                    .setStyles(if (place.placeId == selectedPlaceId) selectedStyle else defaultStyle)
                    .setTag(place.placeId)
                    .setClickable(true)
            )
        }
    }
    LaunchedEffect(kakaoMap, places, selectedPlaceId) {
        val map = kakaoMap ?: return@LaunchedEffect
        val selectedPosition = places.firstOrNull { it.placeId == selectedPlaceId }?.mapPosition()
        val coordinates = places.mapNotNull { it.mapPosition() }
        if (coordinates.isEmpty()) return@LaunchedEffect
        if (selectedPosition != null) {
            map.moveCamera(CameraUpdateFactory.newCenterPosition(selectedPosition))
        } else {
            map.moveCamera(CameraUpdateFactory.fitMapPoints(coordinates.toTypedArray(), 100))
        }
    }
    LaunchedEffect(kakaoMap, pins) {
        val map = kakaoMap ?: return@LaunchedEffect
        if (pins.isNotEmpty() && places.isEmpty() && focusCoordinate == null) {
            map.moveCamera(CameraUpdateFactory.fitMapPoints(
                pins.map { LatLng.from(it.first, it.second) }.toTypedArray(),
                50
            ))
        }
    }
    LaunchedEffect(kakaoMap, focusCoordinate, radiusMeters) {
        val map = kakaoMap ?: return@LaunchedEffect
        val center = focusCoordinate ?: return@LaunchedEffect
        val radius = radiusMeters ?: return@LaunchedEffect
        val angularRadius = radius / 6371000.0
        val latitude = Math.toRadians(center.lat)
        val longitude = Math.toRadians(center.lon)
        val boundary = (0..72).map { index ->
            val bearing = 2 * Math.PI * index / 72
            val ringLatitude = kotlin.math.asin(
                kotlin.math.sin(latitude) * kotlin.math.cos(angularRadius)
                    + kotlin.math.cos(latitude) * kotlin.math.sin(angularRadius) * kotlin.math.cos(bearing)
            )
            val ringLongitude = longitude + kotlin.math.atan2(
                kotlin.math.sin(bearing) * kotlin.math.sin(angularRadius) * kotlin.math.cos(latitude),
                kotlin.math.cos(angularRadius) - kotlin.math.sin(latitude) * kotlin.math.sin(ringLatitude)
            )
            LatLng.from(Math.toDegrees(ringLatitude), Math.toDegrees(ringLongitude))
        }
        map.shapeManager?.layer?.apply {
            removeAll()
            addPolygon(com.kakao.vectormap.shape.PolygonOptions.from(
                com.kakao.vectormap.shape.MapPoints.fromLatLng(boundary),
                com.kakao.vectormap.shape.PolygonStyles.from(0x220878F9, 3f, 0xFF0878F9.toInt())
            ))
        }
        map.moveCamera(CameraUpdateFactory.fitMapPoints(boundary.toTypedArray(), 24))
    }
    AndroidView(factory = { mapView }, modifier = modifier)
}

private fun PlaceSearchResponse.mapPosition(): LatLng? {
    val placeLatitude = latitude ?: return null
    val placeLongitude = longitude ?: return null
    if (placeLatitude !in -90.0..90.0 || placeLongitude !in -180.0..180.0) return null
    return LatLng.from(placeLatitude, placeLongitude)
}
