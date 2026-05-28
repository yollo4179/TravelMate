import axios from 'axios'
import { useAuthStore } from '@/piniaStores/AuthStore'
import { DebugManager } from '@/utils/DebugManager'

export async function refreshAccessToken() {
  const authStore = useAuthStore()
  try {
    const response = await axios.post(
      '/api/auth/refresh',
      null,
      { withCredentials: true },
      //리프레시 토큰은 HttpOnly 쿠키로 전달되므로, 쿠키 함께 보냄
    )

    const token =
      response.headers['authorization'] || response.data.token || response.data.accessToken
    if (token) {
      const newAccessToken = token
      authStore.setAccessToken(newAccessToken)
      return newAccessToken
    } else {
      DebugManager.DebugConsolelog('AuthService', 'refreshAccessToken: no new token returned')
      return null
    }
  } catch (e) {
    DebugManager.DebugConsolelog('AuthService', e)
    throw e
  }
}
export async function logout() {
  const authStore = useAuthStore()
  try {
    await axios.post('/api/auth/logout', null, {
      withCredentials: true,
      headers: {
        Authorization: `Bearer ${authStore.accessToken}`,
      },
    })
    authStore.removeAccessToken() // 액세스 토큰 제거
    // Refresh Token은 HttpOnly 쿠키라 여기서 삭제 불가.
    // 서버가 empty Refresh Token 쿠키로 응답
    window.location.href = '/login'
  } catch (e) {
    DebugManager.DebugConsolelog('AuthService', e)
    throw e
  }
}
export async function login({ userId, password }) {
  const authStore = useAuthStore()
  try {
    const response = await axios.post(
      '/api/auth/login',
      {
        userId,
        password,
      },
      {
        withCredentials: true,
      },
    )

    const loginResult = response.data
    const accessToken = loginResult.accessToken || loginResult.token

    if (accessToken) {
      authStore.setAccessToken(accessToken)
      DebugManager.DebugConsolelog('AuthService', `Login successful, accessToken: ${accessToken}`)
    }

    return loginResult
  } catch (e) {
    DebugManager.DebugConsolelog('AuthService', e)
    throw e
  }
}
