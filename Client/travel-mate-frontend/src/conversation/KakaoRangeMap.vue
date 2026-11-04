<script setup>
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { loadKakaoMaps } from './kakaoMap'
const props = defineProps({
  latitude: Number,
  longitude: Number,
  radius: Number,
  places: { type: Array, default: () => [] },
})
const emit = defineEmits(['select', 'unavailable'])
const container = ref(null)
// Kakao objects are not reactive data; shallowRef avoids deep proxies over SDK instances.
const kakao = shallowRef(null)
let placeMarkers = []

function select(position) {
  emit('select', { latitude: position.getLat(), longitude: position.getLng() })
}
function drawRange() {
  const { maps, map, circle, center } = kakao.value
  const position = new maps.LatLng(props.latitude, props.longitude)
  circle.setPosition(position)
  circle.setRadius(props.radius)
  center.setPosition(position)
  map.setBounds(circle.getBounds())
}
function drawPlaces() {
  const { maps, map } = kakao.value
  placeMarkers.forEach((marker) => marker.setMap(null))
  placeMarkers = props.places
    .filter((place) => Number.isFinite(place.latitude) && Number.isFinite(place.longitude))
    .map(
      (place) =>
        new maps.Marker({
          map,
          position: new maps.LatLng(place.latitude, place.longitude),
          title: place.name,
        }),
    )
}
onMounted(async () => {
  try {
    const maps = await loadKakaoMaps()
    const position = new maps.LatLng(props.latitude, props.longitude)
    const map = new maps.Map(container.value, { center: position })
    const circle = new maps.Circle({
      map,
      center: position,
      radius: props.radius,
      strokeWeight: 2,
      strokeColor: '#288bce',
      strokeOpacity: 0.8,
      strokeStyle: 'dash',
      fillColor: '#2e9cdb',
      fillOpacity: 0.15,
    })
    const center = new maps.Marker({ map, position, draggable: true })
    maps.event.addListener(map, 'click', (event) => select(event.latLng))
    maps.event.addListener(center, 'dragend', () => select(center.getPosition()))
    kakao.value = { maps, map, circle, center }
    drawRange()
    drawPlaces()
  } catch (failure) {
    emit('unavailable', failure.message)
  }
})
watch(
  () => [props.latitude, props.longitude, props.radius],
  () => kakao.value && drawRange(),
)
watch(
  () => props.places,
  () => kakao.value && drawPlaces(),
)
onBeforeUnmount(() => placeMarkers.forEach((marker) => marker.setMap(null)))
</script>
<template>
  <section class="range-map" aria-label="카카오 지도 검색 범위">
    <div class="map-label">기준 핀과 검색 범위 <span>지도를 누르거나 핀을 끌어 이동</span></div>
    <div ref="container" class="kakao-map" role="application" aria-label="카카오 지도"></div>
    <p>
      핀 중심 {{ latitude.toFixed(5) }}, {{ longitude.toFixed(5) }} · 반경
      {{ radius.toLocaleString() }}m
    </p>
    <small>원은 검색 반경이며 도로·도보 경로·이동시간을 나타내지 않습니다.</small>
  </section>
</template>
<style scoped>
.range-map {
  background: #edf6f6;
  border-radius: 20px;
  padding: 16px;
  color: #24465d;
  overflow: hidden;
}
.map-label {
  font-weight: 700;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.map-label span {
  font-weight: 400;
  font-size: 0.8rem;
}
.kakao-map {
  width: 100%;
  aspect-ratio: 1 / 1;
  max-height: 360px;
  margin-top: 10px;
  border-radius: 14px;
}
</style>
