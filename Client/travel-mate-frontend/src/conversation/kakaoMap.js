// The SDK is requested only when a key is configured (VITE_KAKAO_MAP_APP_KEY in .env.local, Git-ignored).
// Without it the coordinate view stays and says the background map is not connected.
const SDK_URL = 'https://dapi.kakao.com/v2/maps/sdk.js'
export const KakaoMapKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY || ''
let loading = null

export function loadKakaoMaps() {
  if (!KakaoMapKey) return Promise.reject(new Error('카카오 지도 키가 설정되지 않았습니다.'))
  if (window.kakao?.maps?.LatLng) return Promise.resolve(window.kakao.maps)
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `${SDK_URL}?appkey=${encodeURIComponent(KakaoMapKey)}&autoload=false`
    script.async = true
    script.onload = () => window.kakao.maps.load(() => resolve(window.kakao.maps))
    script.onerror = () => {
      loading = null
      reject(new Error('카카오 지도 SDK를 불러오지 못했습니다. 키의 도메인 등록을 확인해 주세요.'))
    }
    document.head.appendChild(script)
  })
  return loading
}
