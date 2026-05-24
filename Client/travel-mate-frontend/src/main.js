import { createApp } from 'vue'
import { createPinia } from 'pinia'

import 'bootstrap-icons/font/bootstrap-icons.css'
import App from './App.vue'
import router from './router'
import 'bootstrap/dist/css/bootstrap.min.css'
import axios from 'axios'
import { API_CONFIG, STORAGE_KEYS } from './utils/Constants'
import { DebugManager } from './utils/DebugManager'
const app = createApp(App)

const TAG_API_INTERCEPTORS = 'API_INTERCEPTOORS'
axios.defaults.baseURL = `${API_CONFIG.BASE_API_URL}`
axios.defaults.timeout = 5000
axios.defaults.withCredentials = true
axios.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN)
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error), // 요청 후 예외 던지기
)

axios.interceptors.response.use(
  (response) => response, //통과

  async (error) => {
    //예외 던진 경우
    const originalRequest = error.config
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
        localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, newAccessToken)

        originalRequest.headers['Authorization'] = newAccessToken
        return axios(originalRequest)
      } catch (refreshError) {
        DebugManager.DebugConsolelog(
          TAG_API_INTERCEPTORS,
          'Refresh Token이 만료되었거나 유효하지 않습니다. 로그아웃 처리합니다.',
        )
        localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN)
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
app.use(createPinia())
app.use(router)

app.mount('#app')
