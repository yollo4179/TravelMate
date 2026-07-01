package com.ssafy.travelmate.components

import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ViewGroup
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import com.kakao.vectormap.KakaoMap
import com.kakao.vectormap.MapLifeCycleCallback
import com.kakao.vectormap.MapView
import com.kakao.vectormap.KakaoMapReadyCallback
import com.kakao.vectormap.LatLng
import com.kakao.vectormap.label.LabelOptions
import com.kakao.vectormap.label.LabelStyle
import com.kakao.vectormap.label.LabelStyles


@Composable
fun MapContent(
    pins: List<Pair<Double, Double>> = listOf(),// 이미 저장된 핀 좌표 목록 (서버에서 받아옴)
    onPinAdded: (lat: Double, lng: Double) -> Unit = { _, _ -> },
    modifier: Modifier
){
    var kakaoMap: KakaoMap? = null

    var  gestureDetector :GestureDetector? = null




    Box(modifier = modifier.fillMaxSize()) {
        AndroidView(
            factory = { context ->
                val mapView = MapView(context).apply {
                    layoutParams = ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT
                    )
                    start(
                        object : MapLifeCycleCallback() {
                            override fun onMapDestroy() {
                                // 지도 소멸 시 정리
                            }

                            override fun onMapError(error: Exception) {
                                // 지도 로딩 실패 처리 (인증 실패 등)
                            }
                        },
                        object : KakaoMapReadyCallback() {
                            override fun getPosition(): LatLng {
                                // 여기서 "어디를 중심으로 지도를 띄울지" 직접 지정
                                return LatLng.from(37.5665, 126.9780) // 서울시청
                            }
                            override fun onMapReady(map: KakaoMap) {
                                kakaoMap = map
                                // 기존 핀들 표시
                                pins.forEach { (lat, lng) ->
                                    addPinLabel(map, lat, lng)
                                }

                            }
                        }
                    )
                }
                val gestureDetector = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
                    override fun onLongPress(e: MotionEvent) {
                        val position = kakaoMap?.fromScreenPoint(e.x.toInt(), e.y.toInt()) ?: return
                        onPinAdded(position.latitude, position.longitude)
                    }
                })
                mapView.setOnTouchListener { _, event ->
                    gestureDetector.onTouchEvent(event)
                    false
                }
                mapView
            },
            update = { mapView ->
                //리컴포즈 로직
                // pins 리스트가 바뀔 때 마커 갱신 로직이 필요하면 여기서 처리
                // (간단한 MVP 단계에서는 최초 onMapReady에서만 그려도 무방)
            }
        )
    }
}

private fun addPinLabel(map: KakaoMap, lat: Double, lng: Double) {
    val labelLayer = map.labelManager?.layer
    val style = LabelStyles.from(LabelStyle.from(/* 마커 아이콘 리소스 ID */ android.R.drawable.ic_menu_mylocation))
    labelLayer?.addLabel(
        LabelOptions.from(LatLng.from(lat, lng)).setStyles(style)
    )
}

fun <T1,T2>dummyFun(lat: T1, lng: T2){
}

/*
<meta-data
    android:name="com.kakao.sdk.AppKey"
    android:value="${kakaoNativeAppKey}" />
"무엇을 로드할지"는 사실 거의 다
카카오 디벨로퍼스 콘솔에 등록된 정보와 AndroidManifest.xml의
com.kakao.sdk.AppKey 메타데이터에서 나옵니다.
* MapView.start(...)가 실행되면 SDK는 내부적으로 이 메타데이터를 읽어서
* 네이티브 앱 키를 가져옵니다. 그 키를 가지고 카카오 서버에
* "이 앱 키로 등록된 앱이 지도를 요청한다"고 인증 요청을 보냅니다.
*  즉 "무엇을 로드할지"의 첫 단계는 우리 코드가 아니라 매니페스트에 박혀있는 앱 키이고,
*  이 키에 대응하는 설정(어떤 지도 제품을 쓸 수 있는지,
* 일일 호출 한도 등)은 카카오 디벨로퍼스 콘솔에 이미 등록되어 있습니다.
*
* */