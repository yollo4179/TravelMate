package com.ssafy.travelmate.data.remote.dto.responses.login

data class UserInfoResponse(
    val uid: String,
    val nickname: String,
    val profileImgUrl: String?,
    val email: String?,
    val role: String
)
data class LoginResponse(
    val isNewUser : Boolean,      // 신규 유저인가?
    val tempToken : String ,       // 신규 유저용 5분짜리 임시 토큰 (Register Token)
    val accessToken : String ,     // 기존 유저용 (신규면 null)
    val refreshToken : String      // 기존 유저용 (신규면 null)
)
//RTR방식으로 리프레시는 헤더로, 토큰은 바디로 전송 
data class RefreshResponse(
    val refreshToken: String,
    val accessToken: String
)
//CryptedSharedPreferences에 저장함