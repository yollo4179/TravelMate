import { defineStore } from 'pinia'
import { ref } from 'vue'

/* 로컬 스토리지에 저장하면 xss 공격에 취약 + cookie에 하면 csrf에 취약 
*/
export const useAuthStore = defineStore('Auth', () => {
 
  const accessToken = ref('')
  

  const isInitialized = ref(false)

  function setAccessToken(token) {
    accessToken.value = token
  }

  function removeAccessToken() {
    accessToken.value = ''
  }

  return {
    accessToken,
    isInitialized, 
    setAccessToken,
    removeAccessToken,
  }
})