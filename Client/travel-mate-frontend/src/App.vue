<template>
  <div v-if="!authStore.isInitialized" class="global-loader">
    <div class="loader-content">
      <h2>Travel-Mate를 불러오는 중입니다...</h2>
    </div>
  </div>

  <div v-else>
    <Navbar />
    <router-view />
  </div>
</template>

<script setup>
import Navbar from './components/Navbar.vue' // 방금 만든 네비게이션 임포트
import { DebugManager } from './utils/DebugManager.js'
import { onMounted } from 'vue'
import { refreshAccessToken } from '@/Services/AuthService'
import { UpdateAuthUserProfile } from '@/Services/UserService'
import { useAuthStore } from '@/piniaStores/AuthStore'
const authStore = useAuthStore()

/*Refresh 이벤트를 처리합니다. */
const initAuthApp = async () => {
  try {
    await refreshAccessToken()
    await UpdateAuthUserProfile()
    console.log('새로고침 후 토큰 재발급 및 프로필 로드 완료')
  } catch (error) {
    DebugManager.DebugConsolelog(`리프레시 토큰 만료 또는 없음:${error} -> 로그인 페이지로 이동`)
    // router.push('/login');
  } finally {
    authStore.isInitialized = true
  }
}
initAuthApp()
</script>

<style>
/* 전역 스타일 설정 */
body {
  margin: 0;
  font-family: Arial, sans-serif;
  background-color: #f5f5f5;
}
.main-content {
  padding: 2rem;
}
.global-loader {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 9999;
}
</style>
