<script setup>
import { ref } from 'vue'
import axios from 'axios'
import { DebugManager } from '@/utils/DebugManager'
import { STORAGE_KEYS } from '@/utils/Constants'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/piniaStores/MyStore'
import { useAuthStore } from '@/piniaStores/AuthStore'
const TAG = 'LOGIN_VIEW'
const userId = ref('')
const password = ref('')
const router = useRouter()

const userStore = useUserStore()
const authStore = useAuthStore()

const handleLogin = async () => {
  if (!userId.value || !password.value) {
    alert('아이디와 비밀번호를 모두 입력해주세요.')
    return
  }

  try {
    const response = await axios.post(
      `/api/auth/login`,
      {
        userId: userId.value,
        password: password.value,
      },
      {
        withCredentials: true,
      },
    )

    DebugManager.DebugConsolelog(JSON.stringify(response))
    const loginResult = response.data
    const accessToken = loginResult.accessToken || loginResult.token
    if (accessToken) {
      authStore.setAccessToken(accessToken)
      userStore.setUser({
        uid: loginResult.uid,
        nickname: loginResult.nickname,
        profileImgUrl: loginResult.profileImgUrl,
        role: loginResult.role,
      })

      if (loginResult.grantType) {
        localStorage.setItem(STORAGE_KEYS.GRANT_TYPE, loginResult.grantType)
      }
      DebugManager.DebugConsolelog(TAG, `발급된 토큰: ${accessToken}  
      닉네임${userStore.userNickname}`)

      router.push('/')
    } else {
      DebugManager.DebugConsolelog(
        '로그인은 된 것 같은데 토큰이 안 넘어왔습니다. 응답 구조를 확인해야 합니다.',
      )
    }
  } catch (error) {
    DebugManager.DebugConsolelog(TAG, `로그인 실패:${error}`)
    // 403이나 401 에러가 뜨면 여기서 잡힙니다.
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h2>Travel-Mate</h2>

      <div class="input-group">
        <label for="userId">아이디</label>
        <input v-model="userId" type="text" id="userId" placeholder="아이디를 입력하세요" />
      </div>

      <div class="input-group">
        <label for="password">비밀번호</label>
        <input
          v-model="password"
          type="password"
          id="password"
          placeholder="비밀번호를 입력하세요"
        />
      </div>

      <button @click="handleLogin" class="login-btn">로그인</button>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background-color: #f5f7fa;
}

.login-card {
  background: white;
  padding: 40px;
  border-radius: 12px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
  width: 100%;
  max-width: 400px;
}

h2 {
  text-align: center;
  margin-bottom: 30px;
  color: #333;
}

.input-group {
  margin-bottom: 20px;
  display: flex;
  flex-direction: column;
}

.input-group label {
  margin-bottom: 8px;
  font-size: 14px;
  color: #666;
}

.input-group input {
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 16px;
}

.login-btn {
  width: 100%;
  padding: 14px;
  background-color: #4f46e5;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  font-weight: bold;
}

.login-btn:hover {
  background-color: #4338ca;
}
</style>
