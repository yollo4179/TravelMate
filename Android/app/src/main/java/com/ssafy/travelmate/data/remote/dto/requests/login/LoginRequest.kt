package com.ssafy.travelmate.data.remote.dto.requests.login

data class LoginRequest(
    val idToken: String,
    val provider: String // "GOOGLE" , "KAKAO" , "NAVER"
)

data class OAuthSignupRequest(
    val nickname: String//일단 닉네임만 받습니다.
)
