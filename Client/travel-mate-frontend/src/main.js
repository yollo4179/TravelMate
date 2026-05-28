import { createApp } from 'vue'
import { createPinia } from 'pinia'

import 'bootstrap-icons/font/bootstrap-icons.css'
import App from './App.vue'
import router from './router'
import 'bootstrap/dist/css/bootstrap.min.css'
import axios from 'axios'
import { useAuthStore } from '@/piniaStores/AuthStore'
import { API_CONFIG, STORAGE_KEYS } from './utils/Constants'
import { DebugManager } from './utils/DebugManager'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

const TAG_API_INTERCEPTORS = 'API_INTERCEPTOORS'
axios.defaults.baseURL = `${API_CONFIG.BASE_API_URL}`
axios.defaults.timeout = 5000
axios.defaults.withCredentials = true
const authStore = useAuthStore()

/**********(모든)API 요청할 때마다 액세스 토큰 헤더에 실어서 보내게************* */
axios.interceptors.request.use(
  (config) => {
    const token = authStore.accessToken
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error), // 요청 후 예외 던지기
)
/**********(모든)API 요청할 때마다 "실패 시(기간 만료)" 액세스 + Refresh로 토큰 재발급************* */
axios.interceptors.response.use(
  (response) => response, //통과

  async (error) => {
    //예외 던진 경우
    const originalRequest = error.config
    if (originalRequest.url.includes('/refresh') || originalRequest.url.includes('/logout')) {
      return Promise.reject(error)
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true

      try {
        console.log('Access Token 만료. 토큰 재발급(Refresh) 시도.')

        DebugManager.DebugConsolelog(
          TAG_API_INTERCEPTORS,
          'Access Token 만료 감지. 토큰 재발급(Refresh)을 시도합니다.',
        )
        const refreshResponse = await axios.post('/api/auth/refresh')

        const newAccessToken = refreshResponse.data.accessToken
        if (newAccessToken) {
          authStore.setAccessToken(newAccessToken)
          DebugManager.DebugConsolelog(
            TAG_API_INTERCEPTORS,
            `새 Access Token 발급 성공: ${newAccessToken}`,
          )
        } else {
          DebugManager.DebugConsolelog(
            TAG_API_INTERCEPTORS,
            '새 Access Token이 응답에 포함되어 있지 않습니다.',
          )
          return Promise.reject(error)
        }

        originalRequest.headers['Authorization'] = newAccessToken
        return axios(originalRequest)
      } catch (refreshError) {
        DebugManager.DebugConsolelog(
          TAG_API_INTERCEPTORS,
          'Refresh Token이 만료되었거나 유효하지 않습니다. 로그아웃 처리합니다.',
        )
        authStore.removeAccessToken() // 액세스 토큰 제거
        // Refresh Token은 HttpOnly 쿠키라 여기서 삭제 불가. 서버에 로그아웃 요청 추천.
        await axios.post('/api/auth/logout')
        window.location.href = '/login'
        return Promise.reject(refreshError)
      }
    }
    return Promise.reject(error)
  },
)
export default axios
app.use(router)

app.mount('#app')
