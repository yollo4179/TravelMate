<template>
  <nav class="navbar">
    <div class="nav-brand">
      <router-link to="/" class="brand-logo">✈️ TravelMate</router-link>
    </div>

    <div class="nav-menu">
      <template v-if="!isLoggedIn">
        <router-link to="/login" class="nav-item">로그인</router-link>
        <router-link to="/signup" class="nav-item signup-btn">회원가입</router-link>
      </template>

      <template v-else>
        <router-link to="/logout" @click="logout" class="nav-item logout-btn">로그아웃</router-link>
      </template>
    </div>
  </nav>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { STORAGE_KEYS } from '@/utils/Constants'

const router = useRouter()
const route = useRoute()
const isLoggedIn = ref(false)


const checkLoginStatus = () => {
  isLoggedIn.value = !!localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN)
}
/*로그 아웃 기능만 구현합니다( 토큰 없앱니다.) */
const logout = ()=>{
    localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN)
    localStorage.removeItem(STORAGE_KEYS.REFRESH_TOKEN)
    isLoggedIn.value = false
    router.push('/')
}


onMounted(() => {
  checkLoginStatus()
})

//일단 PATH만 추적... 바뀌면 적법한 루트인지 확인 .
watch(
  () => route.path,
  () => {
    checkLoginStatus()
  },
)
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
  color: #42b883; /* Vue 시그니처 그린 색상 */
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

/* 회원가입 버튼 강조 스타일 */
.signup-btn {
  background-color: #42b883;
  color: white;
  padding: 0.4rem 0.8rem;
  border-radius: 4px;
}

.signup-btn:hover {
  background-color: #35495e;
}

/* 로그아웃 버튼 스타일 */
.logout-btn {
  background-color: transparent;
  border: 1px solid #ff4d4d;
  color: #ff4d4d;
  padding: 0.4rem 0.8rem;
  border-radius: 4px;
}

.logout-btn:hover {
  background-color: #ff4d4d;
  color: white;
}
</style>
