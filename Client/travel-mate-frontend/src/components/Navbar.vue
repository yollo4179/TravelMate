<template>
  <nav class="navbar">
    <div class="nav-brand">
      <router-link to="/" class="brand-logo">✈️ TravelMate</router-link>
    </div>

    <div class="nav-menu">
      <template v-if="!userStore.isAuthenticated">
        <router-link to="/login" class="nav-item">로그인</router-link>
        <router-link to="/signup" class="nav-item signup-btn">회원가입</router-link>
      </template>

      <template v-else>
        <div class="user-profile">
          <img
            :src="userStore.userDesc?.profileImgUrl || '/images/default-avatar.png'"
            alt="프로필"
            class="profile-img"
          />
          <span class="nickname"
            ><strong>{{ userStore.userNickname }}</strong
            >님</span
          >
        </div>

        <a href="#" @click.prevent="logout" class="nav-item logout-btn">로그아웃</a>
      </template>
    </div>
  </nav>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { DebugManager } from '@/utils/DebugManager'

import { useUserStore } from '@/piniaStores/MyStore'
import { useAuthStore } from '@/piniaStores/AuthStore'
import { logout as apiLogout } from '@/Services/AuthService'

const router = useRouter()
const userStore = useUserStore()
const authStore = useAuthStore()

/* 로그아웃 기능: 서버 로그아웃 호출하고 Pinia 상태만 초기화합니다. */
const logout = async () => {
  try {
    await apiLogout()
  } catch (e) {
    DebugManager.DebugConsolelog('LOGOUT', '서버 로그아웃 통신 실패 (이미 만료됨 등):', e)
  } finally {
    // Pinia 상태 초기화
    authStore.removeAccessToken()
    userStore.logout()
    router.push('/')
  }
}
</script>

<style scoped>
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.8rem 2rem;
  background-color: #1a1a1a;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.brand-logo {
  font-size: 1.4rem;
  font-weight: bold;
  color: #42b883;
  text-decoration: none;
}

.nav-menu {
  display: flex;
  align-items: center;
  gap: 1.2rem;
}

.nav-item {
  color: #cccccc;
  text-decoration: none;
  font-size: 1rem;
  transition: color 0.2s;
}

.nav-item:hover {
  color: #ffffff;
}

/* ⭐️ 유저 프로필 관련 스타일 추가 */
.user-profile {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-right: 1rem;
}

.profile-img {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid #42b883;
}

.nickname {
  font-size: 0.95rem;
  color: #ffffff;
}

.signup-btn {
  background-color: #42b883;
  color: white;
  padding: 0.4rem 0.8rem;
  border-radius: 4px;
}

.signup-btn:hover {
  background-color: #35495e;
}

.logout-btn {
  background-color: transparent;
  border: 1px solid #ff4d4d;
  color: #ff4d4d;
  padding: 0.4rem 0.8rem;
  border-radius: 4px;
  cursor: pointer;
}

.logout-btn:hover {
  background-color: #ff4d4d;
  color: white;
}
</style>
