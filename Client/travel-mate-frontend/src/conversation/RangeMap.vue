<script setup>
import { computed } from 'vue'
const props = defineProps({
  latitude: Number,
  longitude: Number,
  radius: Number,
  places: { type: Array, default: () => [] },
})
const emit = defineEmits(['select'])
const latitudeScale = computed(() => (props.radius * 3) / 111320)
const longitudeScale = computed(
  () => latitudeScale.value / Math.max(0.01, Math.cos((props.latitude * Math.PI) / 180)),
)
const pins = computed(() =>
  props.places
    .filter((place) => Number.isFinite(place.latitude) && Number.isFinite(place.longitude))
    .map((place) => ({
      ...place,
      x: 50 + ((place.longitude - props.longitude) / longitudeScale.value) * 100,
      y: 50 - ((place.latitude - props.latitude) / latitudeScale.value) * 100,
    })),
)
function select(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  emit('select', {
    latitude:
      props.latitude - ((event.clientY - rect.top) / rect.height - 0.5) * latitudeScale.value,
    longitude:
      props.longitude + ((event.clientX - rect.left) / rect.width - 0.5) * longitudeScale.value,
  })
}
</script>
<template>
  <section class="range-map" aria-label="좌표 기반 검색 범위 지도">
    <div class="map-label">기준 핀과 검색 범위 <span>좌표 보기 · 배경 지도 미연결</span></div>
    <svg viewBox="0 0 100 100" @click="select" role="img" aria-label="클릭해 기준 핀 이동">
      <defs>
        <pattern id="grid" width="10" height="10" patternUnits="userSpaceOnUse">
          <path d="M 10 0 L 0 0 0 10" fill="none" stroke="#c8dfe5" stroke-width=".25" />
        </pattern>
      </defs>
      <rect width="100" height="100" fill="url(#grid)" />
      <circle
        cx="50"
        cy="50"
        r="33.33"
        fill="#2e9cdb"
        fill-opacity=".15"
        stroke="#288bce"
        stroke-width=".5"
        stroke-dasharray="1 1"
      />
      <g v-for="place in pins" :key="place.placeId">
        <circle :cx="place.x" :cy="place.y" r="1.3" fill="#ef886b" />
        <text :x="place.x + 2" :y="place.y" font-size="2.4">{{ place.name }}</text>
      </g>
      <circle cx="50" cy="50" r="1.5" fill="#1977c5" stroke="white" stroke-width=".5" />
      <text x="52" y="49" font-size="2.8" fill="#165181">기준 위치</text>
    </svg>
    <p>
      핀 중심 {{ latitude.toFixed(5) }}, {{ longitude.toFixed(5) }} · 반경
      {{ radius.toLocaleString() }}m
    </p>
    <small>실제 검색 좌표를 표시합니다. 도로·도보 경로·이동시간을 나타내지 않습니다.</small>
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
.map-label span,
small {
  font-size: 11px;
  font-weight: 400;
  color: #6b858b;
}
svg {
  width: 100%;
  max-height: 350px;
  cursor: crosshair;
}
p {
  font-size: 12px;
  margin: 0;
}
small {
  display: block;
  margin-top: 6px;
}
</style>
