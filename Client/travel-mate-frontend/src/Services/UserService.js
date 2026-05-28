import axios from 'axios'
import { useUserStore } from '@/piniaStores/MyStore'
import { useAuthStore } from '@/piniaStores/AuthStore'



export async function checkUserId(userId) {
  const response = await axios.post('/api/users/checkUserId', { userId }, { withCredentials: true })
  return response.data
}

export async function checkNickname(nickname) {
  const response = await axios.post(
    '/api/users/checkNickname',
    { nickname },
    { withCredentials: true },
  )
  return response.data
}

export async function signUp({ userId, email, password, nickname }) {
  const response = await axios.post(
    '/api/users/signup',
    {
      userId,
      email,
      password,
      nickname,
    },
    { withCredentials: true },
  )
  return response.data
}

export async function getUserProfile() {
  const response = await axios.get('/api/users/me', {
    withCredentials: true,
    headers: {
      Authorization: `Bearer ${useAuthStore().accessToken}`,
    },
  })
  console.log(`getUserProfile response:${useAuthStore().accessToken}`)
  return response.data
}

export async function updateUser({ nickname, profileImgUrl, password }) {
  const response = await axios.put(
    '/api/users/me',
    {
      nickname,
      profileImgUrl,
      password,
    },
    { withCredentials: true },
  )
  return response.data
}

export async function deleteUser() {
  const response = await axios.delete('/api/users/me', {
    withCredentials: true,
  })
  return response.data
}

export async function UpdateAuthUserProfile() {
  const userStore = useUserStore()
  const response = await axios.get('/api/users/me', {
    withCredentials: true,
  })

  const { uid, nickname, profileImgUrl, role, email } = response.data

  const authUser = {
    uid,
    nickname,
    profileImgUrl,
    role,
    email,
  }

  userStore.setUser(authUser)
  return authUser
}
