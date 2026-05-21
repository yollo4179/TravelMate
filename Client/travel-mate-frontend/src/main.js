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
axios.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN)
    if (token) {
      config.headers['X-AUTH-TOKEN'] = token
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
    if (error.response?.status === 401) {
      //같은 요청 방지(재발급을 2번이상 안받음)
      if (originalRequest._retry) {
        return Promise.reject(error)
      }
      originalRequest._retry = true

      try {
        DebugManager.DebugConsolelog(
          TAG_API_INTERCEPTORS,
          'Access Token 만료 감지. 토큰 재발급(Refresh)을 시도합니다.',
        )
        const refreshToken = localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN)

        const refreshResponse = await axios.create()({
          method: 'post',
          url: `${API_CONFIG.BASE_API_URL}/api/refresh`,
          data: { refreshToken: refreshToken },
        })

        const newAccessToken = refreshResponse.data.accessToken
        const newRefreshToken = refreshResponse.data.refreshToken

        localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, newAccessToken)
        localStorage.setItem(STORAGE_KEYS.REFRESH_TOKEN, newRefreshToken)
        //다시 요청
        originalRequest.headers['X-AUTH-TOKEN'] = newAccessToken
        return axios(originalRequest)
      } catch (refreshError) {
        DebugManager.DebugConsolelog(
          TAG_API_INTERCEPTORS,
          'Refresh Token이 만료되었거나 유효하지 않습니다. 로그아웃 처리합니다.',
        )
        localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN)
        localStorage.removeItem(STORAGE_KEYS.REFRESH_TOKEN)
        alert('세션이 만료되었습니다. 다시 로그인해주세요.')
        window.location.href = '/login' // 로그인 페이지로 강제 리다이렉트
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
