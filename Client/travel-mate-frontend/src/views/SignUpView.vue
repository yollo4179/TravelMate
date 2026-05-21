<template>
  <main class="container d-flex justify-content-center align-items-center mt-5">
    <article class="card p-4 shadow-sm w-100" style="max-width: 500px">
      <div class="card-body">
        <h3 class="card-title fw-bold mb-2">회원 가입</h3>
        <p class="card-text text-muted mb-4">회원 가입을 위해서 아래 양식을 작성해주세요.</p>

        <form @submit.prevent="submit" novalidate>
          <div class="mb-3">
            <label for="uname" class="form-label fw-semibold">아이디:</label>
            <div class="d-flex gap-2">
              <input
                type="text"
                class="form-control"
                id="uname"
                ref="userIdInput"
                placeholder="Enter username"
                v-model="userId"
                @focus="isUserIdFocused = true"
                @blur="isUserIdFocused = false"
                required
              />
              <button
                type="button"
                @click="checkUserId"
                class="btn btn-outline-success text-nowrap"
              >
                중복 확인
              </button>
            </div>
            <div
              :style="{
                visibility:
                  (isUserIdFocused || isUserIdValid) && userIdMessage ? 'visible' : 'hidden',
              }"
              :class="isUserIdValid ? 'text-success' : 'text-danger'"
              class="small mt-1"
            >
              {{ userIdMessage || '&nbsp;' }}
            </div>
          </div>

          <div class="mb-3">
            <label for="pwd" class="form-label fw-semibold">비밀번호:</label>
            <input
              type="password"
              class="form-control"
              id="pwd"
              placeholder="Enter password"
              v-model="password"
              @focus="isPasswordFocused = true"
              @blur="isPasswordFocused = false"
              required
            />
            <div
              :style="{
                visibility:
                  isPasswordFocused && password && !isPasswordValid ? 'visible' : 'hidden',
              }"
              class="text-danger small mt-1"
            >
              8자 이상, 영문, 숫자, 특수문자를 포함해야 합니다.
            </div>
          </div>

          <div class="mb-3">
            <label for="email" class="form-label fw-semibold">이메일:</label>
            <input
              type="email"
              class="form-control"
              id="email"
              placeholder="Enter email"
              v-model="email"
              @focus="isEmailFocused = true"
              @blur="isEmailFocused = false"
              required
            />
            <div
              :style="{
                visibility: isEmailFocused && email && !isEmailValid ? 'visible' : 'hidden',
              }"
              class="text-danger small mt-1"
            >
              올바른 이메일 형식이 아닙니다.
            </div>
          </div>

          <div class="mb-3">
            <label for="nickname" class="form-label fw-semibold">닉네임:</label>
            <div class="d-flex gap-2">
              <input
                type="text"
                class="form-control"
                id="nickname"
                ref="nicknameInput"
                placeholder="Enter nickname"
                v-model="nickname"
                @focus="isNicknameFocused = true"
                @blur="isNicknameFocused = false"
                required
              />
              <button
                type="button"
                @click="checkNickname"
                class="btn btn-outline-success text-nowrap"
              >
                중복 확인
              </button>
            </div>
            <div
              :style="{
                visibility:
                  (isNicknameFocused || isNicknameValid) && nicknameMessage ? 'visible' : 'hidden',
              }"
              :class="isNicknameValid ? 'text-success' : 'text-danger'"
              class="small mt-1"
            >
              {{ nicknameMessage || '&nbsp;' }}
            </div>
          </div>

          <div class="form-check mb-2">
            <input
              class="form-check-input"
              type="checkbox"
              id="myCheck"
              v-model="isAgreed"
              required
            />
            <label class="form-check-label" for="myCheck">I agree on blabla.</label>
          </div>

          <div
            :style="{ visibility: showAgreeWarning ? 'visible' : 'hidden' }"
            class="text-danger small mb-4"
          >
            약관 동의가 필요합니다.
          </div>

          <div class="d-grid">
            <button type="submit" :disabled="!isFormValid" class="btn btn-success btn-lg">
              Submit
            </button>
          </div>

          <div
            :style="{ visibility: adviceMessage ? 'visible' : 'hidden' }"
            class="mt-3 text-center text-danger fw-semibold small"
          >
            {{ adviceMessage || '&nbsp;' }}
          </div>
        </form>
      </div>
    </article>
  </main>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { ref, watch, computed } from 'vue'
import axios from 'axios'
import { DebugManager } from '@/utils/DebugManager'

const router = useRouter()
const userId = ref('')
const nickname = ref('')
const email = ref('')
const password = ref('')
const isAgreed = ref(false)

const isUserIdFocused = ref(false)
const isNicknameFocused = ref(false)
const isPasswordFocused = ref(false)
const isEmailFocused = ref(false)

const userIdInput = ref(null)
const nicknameInput = ref(null)

const userIdMessage = ref('')
const isUserIdValid = ref(false)

const nicknameMessage = ref('')
const isNicknameValid = ref(false)
const serverErrorMessage = ref('')

// 이메일 정규식 오타 교정 완료 (0-0 -> 0-9)
const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
const passwordRegex = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[@$!%*#?&])[A-Za-z\d@$!%*#?&]{8,}$/

const isEmailValid = computed(() => emailRegex.test(email.value.trim()))
const isPasswordValid = computed(() => passwordRegex.test(password.value))

watch(userId, () => {
  isUserIdValid.value = false
  userIdMessage.value = ''
})

watch(nickname, () => {
  isNicknameValid.value = false
  nicknameMessage.value = ''
})

const showAgreeWarning = computed(() => {
  return (
    userId.value.trim() &&
    isUserIdValid.value &&
    password.value.trim() &&
    isPasswordValid.value &&
    email.value.trim() &&
    isEmailValid.value &&
    nickname.value.trim() &&
    isNicknameValid.value &&
    !isAgreed.value
  )
})

const adviceMessage = computed(() => {
  if (serverErrorMessage.value) return serverErrorMessage.value
  if (!userId.value.trim()) return '아이디를 입력해주세요.'
  if (!isUserIdValid.value) return '아이디 중복 확인이 필요합니다.'
  if (!password.value.trim()) return '비밀번호를 입력해주세요.'
  if (!isPasswordValid.value) return '비밀번호 요구 조건이 맞지 않습니다.'
  if (!email.value.trim()) return '이메일을 입력해주세요.'
  if (!isEmailValid.value) return '올바른 이메일 형식이 아닙니다.'
  if (!nickname.value.trim()) return '닉네임을 입력해주세요.'
  if (!isNicknameValid.value) return '닉네임 중복 확인이 필요합니다.'
  if (!isAgreed.value) return '약관 동의가 필요합니다.'
  return ''
})

const isFormValid = computed(() => {
  return (
    userId.value.trim() &&
    isUserIdValid.value &&
    password.value.trim() &&
    isPasswordValid.value &&
    email.value.trim() &&
    isEmailValid.value &&
    nickname.value.trim() &&
    isNicknameValid.value &&
    isAgreed.value
  )
})

const submit = async () => {
  if (!isFormValid.value) return

  /* 뚫음 */
  try {
    serverErrorMessage.value = ''
    await axios.post('/api/signup', {
      userId: userId.value,
      email: email.value,
      password: password.value,
      nickname: nickname.value,
    })

    alert('회원가입이 완료되었습니다. 로그인 후 서비스를 이용해주세요.')
    router.replace('/login')
  } catch (error) {
    DebugManager.DebugAlarm(`회원 가입 실패: ${error}`)
    serverErrorMessage.value = '회원가입 중 오류가 발생했습니다. 다시 시도해주세요.'
  }
}

const checkDuplication = async (url, key, value, messageRef, validRef, inputRef) => {
  const typeName = key === 'userId' ? '아이디' : '닉네임'
  if (!value.trim()) {
    messageRef.value = `${typeName}를 입력해주세요.`
    if (inputRef && inputRef.value) inputRef.value.focus()
    return
  }

  try {
    serverErrorMessage.value = ''
    await axios.post(url, { [key]: value }) //동적 키 문법 (값)

    messageRef.value = `사용 가능한 ${typeName}입니다.`
    validRef.value = true
  } catch (error) {
    validRef.value = false

    if (error.response && error.response.status === 409) {
      messageRef.value = `이미 존재하는 ${typeName}입니다.`
    } else {
      messageRef.value = '서버 통신 오류가 발생했습니다.'
    }
  } finally {
    if (inputRef && inputRef.value) inputRef.value.focus()
  }
}

const checkUserId = async () => {
  await checkDuplication(
    '/api/checkUserId',
    'userId',
    userId.value,
    userIdMessage,
    isUserIdValid,
    userIdInput,
  )
}

const checkNickname = async () => {
  await checkDuplication(
    '/api/checkNickname',
    'nickname',
    nickname.value,
    nicknameMessage,
    isNicknameValid,
    nicknameInput,
  )
}
</script>
